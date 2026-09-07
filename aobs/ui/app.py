"""`SignerApp`: the one Textual application, and the display seam itself.

There is no `Screen` port. It was declared with two adapters — "Textual on the console" and
"Textual `run_test()`" — which are the *same* application under two drivers, not two
implementations of an interface. So the app is the seam: tests drive this object headless through
`run_test()`, pressing real keys against real screens, and the console adapter will run the very
same object. `docs/test-harness.md`'s port table says so.

The four ports it is handed are the things that genuinely do have two implementations. The app
never reaches for a camera, for randomness, for a power-off or for the console's keymap by itself.
"""

from __future__ import annotations

from textual.app import App
from textual.binding import Binding

from aobs.core import mnemonic as bip39_words
from aobs.core.constants import ENTROPY_CAMERA_FRAMES, ENTROPY_OUTPUT_BYTES
from aobs.core.entropy import Entropy, MixingReport, mix
from aobs.core.entropy import report as mixing_report
from aobs.core.failure import describe
from aobs.core.release import UNKNOWN, Release
from aobs.core.wallet import Network, Wallet
from aobs.core.wallet_qr import ExportedWallet
from aobs.ports.entropy_source import EntropySource
from aobs.ports.frame_source import FrameSource
from aobs.ports.keymap import Keymap
from aobs.ports.power import Power
from aobs.ui.geometry import MAX_COLUMNS, fits
from aobs.ui.scanning import ScanTarget
from aobs.ui.screens.camera_lost import CameraLostScreen
from aobs.ui.screens.console_too_small import ConsoleTooSmallScreen
from aobs.ui.screens.home import HomeScreen
from aobs.ui.screens.keymap import KeymapScreen
from aobs.ui.screens.scan import INBOUND_FRAME_RATE, ScanScreen

#: How often the randomness wait screen asks whether the kernel's pool has come up. Four times a
#: second: fast enough that the screen is gone before the user has finished reading it on a
#: machine that was nearly ready, slow enough that the poll's own byte draw is not the reason the
#: pool stays busy.
ENTROPY_POLL_INTERVAL = 0.25


class SignerApp(App[None]):
    """The appliance.

    Holds the session: the wallet or the absence of one, the network, whether a camera was found.
    Nothing here ends the session but `F12` and an unrecoverable fault — a refused PSBT returns to
    the scan screen with the wallet still loaded, because dropping it buys nothing (it is in RAM
    regardless, and a refusal means the attack failed) and costs a great deal.
    """

    #: Three reserved keys, identical on every screen, and nothing else reserved
    #: (`docs/failure-states.md`). They are `priority` so that no screen can shadow them: a user
    #: who has learned `esc` means *back* must never meet a screen where it means *proceed*, and
    #: the way to guarantee that is to make the screen unable to claim the key at all.
    #:
    #: The third reserved key is the confirm key, and it is deliberately absent here: it is
    #: per-screen, and only the rule about it is global — never `enter`, never `esc`.
    BINDINGS = [
        Binding("escape", "back", "Back", priority=True),
        Binding("f12", "power_off", "Power off", priority=True),
    ]

    CSS = f"""
    Screen {{ align-horizontal: center; }}
    #frame {{ width: {MAX_COLUMNS}; max-width: 100%; height: 1fr; padding: 1 2; }}
    #title {{ text-style: bold; margin-bottom: 1; }}
    """

    def __init__(
        self,
        *,
        frames: FrameSource,
        entropy: EntropySource,
        power: Power,
        keymap: Keymap,
        network: Network = Network.MAINNET,
        release: Release = UNKNOWN,
        scan_frame_interval: float | None = 1 / INBOUND_FRAME_RATE,
        emit_animated: bool = True,
        entropy_poll_interval: float | None = ENTROPY_POLL_INTERVAL,
    ) -> None:
        super().__init__()
        self.frames = frames
        self.entropy = entropy
        self.power = power
        self.keymap = keymap
        #: What the image says about itself, read once by `aobs/__main__.py` and never again. It is
        #: **not** a fifth port: reading one file has one implementation, and the seam the tests
        #: need is this value being passed in. The default is the development build a source tree
        #: is, so nothing can accidentally look like a release by omitting the argument.
        self.release = release
        #: How often the scan screen pulls a frame. `None` means no timer at all, which is how the
        #: suite drives frames itself: pacing twenty-seven frames in real time would cost the suite
        #: seven seconds to assert something that is not Textual's clock.
        self.scan_frame_interval = scan_frame_interval
        #: Whether the emit screen runs its own 2 fps timer. `False` is how the suite steps the
        #: animation itself: pacing 47 frames in real time would cost it 23 seconds to assert
        #: something that is not Textual's clock.
        self.emit_animated = emit_animated
        #: How often the randomness wait screen asks the `EntropySource` whether the pool is up.
        #: `None` means no timer at all, which is how the suite steps the wait itself.
        self.entropy_poll_interval = entropy_poll_interval

        # --- session state ---
        self.wallet: Wallet | None = None
        #: The words behind `self.wallet`. Held for the session so *show recovery words* can be an
        #: explicit action rather than a promise the appliance cannot keep — `docs/seed-entry.md`
        #: allows this: the words are in RAM regardless, and a user who cannot check their paper
        #: against the appliance either trusts a backup they never verified or writes a second
        #: guess. It is not a second copy of anything; it is the copy the wallet came from.
        self.mnemonic: str | None = None
        #: What `core.mix()` reported, for a wallet generated here. `None` for one typed in or
        #: restored, because there was no mixing to report.
        self.mixing: MixingReport | None = None
        #: Which chain this session is on — `docs/network-selection.md`. Chosen from the wallet
        #: screen before any wallet is constructed, defaulting to mainnet, and `account` stays 0.
        self.network = network
        #: A one-way latch, not a guard on `self.wallet`. The two behave identically today because
        #: nothing clears the wallet, and that is exactly the trap: a later *forget this wallet*
        #: path would quietly re-open network switching, and the same seed could then be restored
        #: onto a different chain with only the header changing. The rule the session actually has
        #: is *fixed for the rest of the session*, so it is the rule that is written down.
        self.network_fixed = False
        self.camera_available = False
        #: What an unrecoverable fault said, for a test to read. Never a traceback.
        self.fatal_message: str | None = None
        #: The bytes the last completed scan produced. This is where the inbound spec ends: what
        #: happens to them is the review, restore and address-verification specs.
        self.scanned: bytes | None = None
        #: One sentence for the screen the user lands on next — how far an abandoned scan got.
        #: Nothing here is attacker-controlled: the appliance writes it about its own state.
        self.notice: str | None = None
        #: The encrypted wallet QR this session has produced, container and password together —
        #: shown apart, always. Held for the session so the eight words stay re-showable after
        #: the export completes: the password is in RAM either way, so refusing to redisplay
        #: protects nothing, while a second export would hand the user a second password that
        #: silently invalidates the paper the first one is written on.
        self.export: ExportedWallet | None = None
        #: The words a wallet-entry path has settled on, waiting for the passphrase. The wallet is
        #: not constructed until then, because `Wallet.from_mnemonic` takes the passphrase and
        #: there is no such thing as adding one afterwards.
        self._pending_mnemonic: str | None = None
        #: The mixing behind those words, when they were generated here. Its presence is also what
        #: tells the fingerprint screen there is nothing to compare against.
        self._pending_entropy: Entropy | None = None

    # --- startup -----------------------------------------------------------------------------

    def on_mount(self) -> None:
        columns, rows = self.size.width, self.size.height
        if not fits(columns, rows):
            # Refuse rather than degrade: a layout that has quietly reflowed is exactly where a
            # truncated address goes unnoticed. Nothing else in the session starts.
            self.push_screen(ConsoleTooSmallScreen(columns, rows))
            return
        self.camera_available = self._camera_present()
        self.push_screen(KeymapScreen())

    def _camera_present(self) -> bool:
        """Ask the `FrameSource` for one frame, once, before any secret exists.

        A source that yields nothing is a machine with no webcam, and that disables the scan paths
        and nothing else — generating a wallet and exporting its descriptor are both outbound and
        need no camera at all.
        """
        return bool(self._pull_frames(1))

    # --- the global keys ---------------------------------------------------------------------

    def action_back(self) -> None:
        """Back out of this screen without acting. Never proceeds, and never leaves nothing.

        The stack holds Textual's own default screen underneath ours, so backing off the first
        real screen would leave the user staring at a blank one. There is nothing behind the first
        screen, so `esc` there does nothing.
        """
        if len(self.screen_stack) > 2:
            # The screen being left says what leaving costs — how far an abandoned scan got —
            # before the screen underneath is asked to redraw. Set after the pop, the notice
            # would be one refresh too late to appear, which is a silence rather than a bug the
            # next reader would notice.
            leaving = getattr(self.screen, "leave_notice", None)
            self.notice = leaving() if leaving is not None else None
            self.pop_screen()

    # --- what the screens call ----------------------------------------------------------------

    def open_scan(self, target: ScanTarget) -> None:
        """Every inbound path goes through the one scan screen.

        The notice and the bytes of the last scan are both dropped here rather than when they are
        read: they describe a scan the user has walked away from, and a stale wallet backup sitting
        in a session attribute is exactly the kind of thing `docs/secret-hygiene.md` is about.
        """
        self.notice = None
        self.scanned = None
        self.push_screen(ScanScreen(target, network=self.network))

    def open_review(self, psbt_bytes: bytes) -> None:
        """The scan screen has a whole PSBT. Review it, and show whichever screen applies.

        The app holds no opinion about a PSBT — `Review.signable` alone chooses between the review
        screen and the refusal, and that choice lives beside the screens that render it.
        """
        from aobs.ui.screens.review import open_review

        open_review(self, psbt_bytes)

    # --- getting a wallet in ------------------------------------------------------------------
    #
    # Three peer paths — generate, type words, scan an encrypted QR — and one shared tail: the
    # passphrase, then the fingerprint. They are peers on the home screen rather than three items
    # under an *import* submenu, because burying the encrypted QR would hide the path two tickets
    # were spent making safe (`docs/seed-entry.md`).

    def open_generate(self) -> None:
        """The dice screen first, and it is the only thing offered before generation.

        Optional in the only sense that matters: `F10` with no rolls at all goes straight on, and
        nothing on the way out says the wallet is worse for it.
        """
        from aobs.ui.screens.dice import DiceScreen

        self.push_screen(DiceScreen())

    def generate_wallet(self, dice_rolls: str) -> None:
        """The entropy-consuming step, with the randomness wait in front of it.

        The wait sits **here** rather than at startup, and that placement is the decision:
        `docs/entropy-mixing.md` sequences entropy-consuming work after user interaction has begun
        precisely so the pool has had a keyboard and a camera generating interrupts for it.
        Moving the wait to boot would guarantee it was not ready.
        """
        if not self.entropy.ready():
            from aobs.ui.screens.entropy_wait import EntropyWaitScreen

            self.push_screen(EntropyWaitScreen(dice_rolls))
            return
        self._generate(dice_rolls)

    def entropy_ready(self, dice_rolls: str) -> None:
        """The pool came up while the wait screen was showing. Go on, without it on the stack."""
        self.pop_screen()
        self._generate(dice_rolls)

    def _generate(self, dice_rolls: str) -> None:
        """One draw from the `EntropySource`, camera frames, and whatever was rolled. 24 words.

        The UI computes no entropy of its own and makes no estimate — `mix()` is handed what the
        screens and the camera produced and nothing else, and the kernel CSPRNG is a required
        argument to it, so there is no reachable path in which dice or frames substitute for it.
        """
        from aobs.ui.screens.recovery_words import RecoveryWordsScreen

        entropy = mix(
            self.entropy.random_bytes(ENTROPY_OUTPUT_BYTES),
            camera_frames=self._entropy_frames(),
            dice_rolls=dice_rolls,
        )
        self._pending_entropy = entropy
        self.push_screen(
            RecoveryWordsScreen(bip39_words.from_entropy(entropy.value), read_back=True)
        )

    def _entropy_frames(self) -> tuple[bytes, ...]:
        """Whole frames for the mixer — `docs/entropy-mixing.md`'s camera source, at last live.

        The camera contributes **in every session, without being asked**, which is a statement the
        project publishes and which this is the first code to keep. It is a small fixed number of
        whole frames, hashed by `mix()`, with **no entropy estimate of any kind**: Krux's one real
        memory-safety failure lived inside a camera entropy estimator, so there is none here to
        get wrong.

        A camera that is absent, covered, or that yields nothing contributes nothing and blocks
        nothing — the mixer is additive and the kernel CSPRNG sets the floor either way. That is
        why every failure below is swallowed rather than shown: there is nothing for the user to
        do about it and nothing about their seed that got worse.
        """
        return self._pull_frames(ENTROPY_CAMERA_FRAMES)

    def _pull_frames(self, count: int) -> tuple[bytes, ...]:
        """At most `count` frames, and whatever the camera managed if it managed fewer.

        The one place the app opens a frame stream of its own — the scan screen runs its own, with
        a timer. **Nothing may be left holding the device**: the adapter holds mapped buffers and
        the next stream of the session opens fresh ones, so a leak here is a camera that works
        once per session. The port promises an `Iterator`, not a generator, so `close()` is not
        guaranteed and is called only if it is there.
        """
        collected: list[bytes] = []
        stream = self.frames.frames()
        try:
            for frame in stream:
                collected.append(frame.data)
                if len(collected) == count:
                    break
        except OSError:
            pass
        finally:
            close = getattr(stream, "close", None)
            if close is not None:
                close()
        return tuple(collected)

    def open_read_back(self, mnemonic: str) -> None:
        """All 24 words, typed back from the paper — the only check that paper will ever get."""
        from aobs.ui.screens.seed_entry import SeedEntryScreen

        self.push_screen(SeedEntryScreen(len(mnemonic.split()), expected=mnemonic))

    def open_seed_entry(self) -> None:
        """The word count first, asked and never detected."""
        from aobs.ui.screens.word_count import WordCountScreen

        self.push_screen(WordCountScreen())

    def open_seed_grid(self, words: int) -> None:
        from aobs.ui.screens.seed_entry import SeedEntryScreen

        self.push_screen(SeedEntryScreen(words))

    # --- receiving and exporting ---------------------------------------------------------------

    def open_address_verify(self, scanned: str) -> None:
        """A scanned address, proved or not proved. The scan screen hands the text straight in;
        whether it is an address at all is this screen's question and needs no camera."""
        from aobs.ui.screens.address_verify import AddressVerifyScreen

        self.push_screen(AddressVerifyScreen(scanned))

    def open_address_list(self) -> None:
        """Twenty at a time — the check that the descriptor export landed intact."""
        from aobs.ui.screens.address_list import AddressListScreen

        self.push_screen(AddressListScreen())

    def open_descriptor(self) -> None:
        """One static `ur:crypto-output`, for the watch-only wallet. No camera needed: outbound."""
        from aobs.ui.screens.descriptor import DescriptorScreen

        self.push_screen(DescriptorScreen())

    def open_wallet_export(self) -> None:
        """Encrypt this session's entropy under a freshly generated eight-word password.

        **Generated once per session and held**, which is what makes the password re-showable for
        the rest of it (`docs/export-password.md`) — and what stops a second visit from handing
        the user a second password that silently invalidates the paper they wrote the first one
        on. It is the same reasoning as the read-back retrying the same password, and it is
        enforced the same way: by there being no second call to `export_wallet()`.

        There is no password parameter to pass and nothing here would have one to pass.
        """
        from aobs.core import mnemonic as bip39_words
        from aobs.core.wallet_qr import export_wallet
        from aobs.ui.screens.wallet_export import WalletQrScreen

        if self.mnemonic is None:  # pragma: no cover - the path needs a wallet to be offered
            return
        if self.export is None:
            self.export = export_wallet(
                bip39_words.to_entropy(self.mnemonic),
                self.entropy.random_bytes,
                network=self.network,
            )
        self.push_screen(WalletQrScreen(self.export))

    def open_export_password(self, container: bytes) -> None:
        """A scanned wallet backup, waiting on its eight words."""
        from aobs.ui.screens.export_password import ExportPasswordScreen

        self.push_screen(ExportPasswordScreen(container))

    def open_recovery_words(self) -> None:
        """*Show recovery words*: an explicit action, never a step on the way to anything else."""
        from aobs.ui.screens.recovery_words import RecoveryWordsScreen

        if self.mnemonic is None:
            return
        self.push_screen(RecoveryWordsScreen(self.mnemonic, read_back=False))

    def open_network(self) -> None:
        """*Choose the network*: a path opened with `F10`, not an arrow key on the home screen.

        Unreachable once `network_fixed` — the home screen renders the path unavailable and
        refuses to open it — so this never has to defend itself against a fixed session.
        """
        from aobs.ui.screens.network import NetworkScreen

        self.push_screen(NetworkScreen(self.network))

    def accept_network(self, network: Network) -> None:
        """The chosen network, back from the picker. Reversible right up until a wallet is made."""
        self.network = network
        self.pop_screen()

    def begin_passphrase(self, mnemonic: str) -> None:
        """The words are settled, whichever path settled them. Ask for the passphrase once."""
        from aobs.ui.screens.passphrase import PassphraseScreen

        self._pending_mnemonic = mnemonic
        self.push_screen(PassphraseScreen())

    def finish_wallet(self, passphrase: str) -> None:
        """Construct the wallet and show its fingerprint. The network was chosen before this.

        Entered once, and never held twice: the passphrase reaches `Wallet.from_mnemonic` and
        nothing else, and the confirmation the user gets is the fingerprint rather than a second
        typing (`docs/secret-hygiene.md`).
        """
        from aobs.ui.screens.fingerprint import FingerprintScreen

        mnemonic = self._pending_mnemonic
        if mnemonic is None:  # pragma: no cover - no path reaches the screen without one
            return
        entropy = self._pending_entropy
        self._pending_mnemonic = None
        self._pending_entropy = None

        wallet = Wallet.from_mnemonic(mnemonic, network=self.network, passphrase=passphrase)
        self.wallet = wallet
        self.mnemonic = mnemonic
        #: The one place the latch closes, because this is the one place a wallet is derived on
        #: the answer. It never re-opens.
        self.network_fixed = True
        self.mixing = mixing_report(entropy, wallet) if entropy is not None else None
        self.switch_screen(
            FingerprintScreen(
                wallet.fingerprint_hex,
                created_here=entropy is not None,
                network=self.network,
                report=self.mixing,
            )
        )

    def return_home(self) -> None:
        """Back to the home screen from wherever a path ended, without walking it backwards."""
        while len(self.screen_stack) > 2:
            self.pop_screen()

    def camera_lost(self) -> None:
        """The camera stopped answering. It cannot come back this session, and the screen says so.

        `authorized_default=0` is set before the first secret exists, so an unplugged and
        replugged camera is not re-authorized. Backing out of the message lands on a home screen
        with the scan paths disabled, which is the honest remainder of the session.
        """
        self.camera_available = False
        self.switch_screen(CameraLostScreen())

    def action_power_off(self) -> None:
        """End the session, from anywhere, always.

        `F12` specifically: hard to hit by accident, impossible to hit while touch-typing a
        mnemonic — and a power-off that needs a menu is one people avoid, which leaves wallets
        loaded on unattended machines.

        The wipe happens **before** the port is called, because the port does not return on the
        appliance. It is a sequence the harness can watch with the recording fake, which is the
        only place a wipe on the way to a power-off can be observed at all.
        """
        self._wipe()
        self.power.power_off()
        self.exit()

    def _wipe(self) -> None:
        """Best-effort wipe of the derived key material the app itself holds. Not erasure.

        `docs/threat-model.md` claim (ii) is worded with exactly that reach, and the wording is
        the honest one: CPython copies `bytes` and `str` freely and the copies cannot be counted,
        so what this does is drop the **retained, long-lived** references this object holds. A
        full RAM overwrite was already rejected as theatre, and nothing here should be read as
        byte-zeroing.
        """
        self.wallet = None
        self.mnemonic = None
        self.mixing = None
        self.export = None
        self.scanned = None
        self._pending_mnemonic = None
        self._pending_entropy = None

    # --- what the keymap picker calls ---------------------------------------------------------

    def accept_keymap(self, name: str) -> None:
        self.keymap.apply(name)
        self.switch_screen(HomeScreen())

    # --- unrecoverable faults -----------------------------------------------------------------

    def fatal(self, error: BaseException) -> str:
        """The whole of what an unrecoverable fault may say: the exception type, and one sentence.

        Not `str(error)`, and above all not a traceback. An exception raised from inside a frame
        holding a mnemonic must not be trusted to be free of it, and a crash renderer drawing that
        frame would defeat every measure in `docs/secret-hygiene.md` in one screenful — at the
        exact moment the user is staring at the display.
        """
        self.fatal_message = describe(error)
        return self.fatal_message

    def _handle_exception(self, error: Exception) -> None:
        """Replace Textual's crash renderer, which is `Traceback(show_locals=True)`.

        Overriding a private method is not something to do lightly, and it is the right call here:
        the default is not a style choice we dislike, it is a renderer that prints local variables
        of every frame on the stack. There is no public hook for this, and leaving the default in
        place would make the appliance's central promise false.
        """
        self._return_code = 1
        if self._exception is None:
            self._exception = error
            self._exception_event.set()
        self._exit_renderables.append(self.fatal(error))
        self._close_messages_no_wait()
