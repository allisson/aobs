"""Getting a wallet in, driven the way the appliance is driven.

Keystrokes in, widget state and session state out. Never a pixel, never a private attribute — every
test here presses real keys against a real `SignerApp` through Textual's `run_test()`, which is the
same object the console adapter runs.

The fixtures are the published BIP39 vectors from `tests/conftest.py`, so nothing here is ever a
live wallet.
"""

from __future__ import annotations

from collections import Counter

import pytest
from textual.widgets import Static

from aobs.adapters.fake import (
    FixedEntropySource,
    ImageFileFrameSource,
    RecordingKeymap,
    RecordingPower,
)
from aobs.core import export_password as eff
from aobs.core import mnemonic as bip39
from aobs.core.constants import ENTROPY_OUTPUT_BYTES, EXPORT_PASSWORD_WORDS
from aobs.core.entropy import mix
from aobs.core.wallet import Network, Wallet
from aobs.core.wallet_qr import export_wallet
from aobs.ui.app import SignerApp
from aobs.ui.screens.dice import OFFER, DiceScreen
from aobs.ui.screens.export_password import (
    NOT_IN_THE_QR,
    WRONG_PASSWORD,
    ExportPasswordScreen,
)
from aobs.ui.screens.fingerprint import COMPARE_IT, RECORD_IT, FingerprintScreen
from aobs.ui.screens.home import CHOOSE_NETWORK, NETWORK_FIXED, PATHS, HomeScreen
from aobs.ui.screens.network import NetworkScreen
from aobs.ui.screens.passphrase import PassphraseScreen
from aobs.ui.screens.recovery_words import RecoveryWordsScreen
from aobs.ui.screens.seed_entry import CHECKSUM_FAILED, READ_BACK_FAILED, SeedEntryScreen
from aobs.ui.screens.word_count import WordCountScreen
from aobs.ui.widgets.secretinput import EMPTY, MASK
from aobs.ui.widgets.wordgrid import WordGrid

from conftest import VECTOR_MNEMONIC, fixed_bytes

CONSOLE = (128, 48)

#: What generation produces from `FixedEntropySource`'s first 32 bytes and no dice. Derived here
#: rather than pasted, so the test states the rule instead of a magic string.
GENERATED = bip39.from_entropy(mix(FixedEntropySource().random_bytes(ENTROPY_OUTPUT_BYTES)).value)


def build(**overrides: object) -> SignerApp:
    ports = {
        "frames": ImageFileFrameSource([]),
        "entropy": FixedEntropySource(),
        "power": RecordingPower(),
        "keymap": RecordingKeymap(),
        "scan_frame_interval": None,
    }
    ports.update(overrides)
    return SignerApp(**ports)  # type: ignore[arg-type]


def texts(app: SignerApp) -> str:
    return "\n".join(str(widget.content) for widget in app.screen.query(Static))


async def reach_home(pilot) -> None:
    await pilot.press("f10")
    await pilot.pause()


async def open_path(pilot, app: SignerApp, name: str) -> None:
    """Walk the home screen to a path by name and open it, from wherever the cursor was left."""
    if not isinstance(app.screen, HomeScreen):
        await reach_home(pilot)
    target = next(i for i, path in enumerate(PATHS) if path.name == name)
    for _ in range((target - PATHS.index(app.screen.selected_path)) % len(PATHS)):
        await pilot.press("down")
    await pilot.press("f10")
    await pilot.pause()


async def type_words(pilot, words) -> None:
    """Type a list of words the way the appliance is meant to be typed on.

    Four characters for anything the BIP39 rule settles there, and the whole of the 103 words too
    short to reach it. Full-word typing has its own test; using it everywhere would cost the suite
    roughly twice the keystrokes to assert the same session state, and `Pilot.press` pays a real
    cost per key.

    Only ever handed BIP39 words: the EFF grid resolves nothing short of a full word, and there is
    a test asserting exactly that.
    """
    keys: list[str] = []
    for word in words:
        keys += [*word[:4], "space"] if len(word) >= 4 else [*word, "space"]
    await pilot.press(*keys)
    await pilot.pause()


async def type_words_in_full(pilot, words) -> None:
    """Every character of every word, committed with a space. The slowest of the entry styles and
    the one a user who has never heard of the shortcut will use."""
    keys: list[str] = []
    for word in words:
        keys += [*word, "space"]
    await pilot.press(*keys)
    await pilot.pause()


# --- The three peer choices ---------------------------------------------------------------------


async def test_the_three_ways_in_are_peers_on_one_screen() -> None:
    """Not an *import* submenu: `docs/seed-entry.md` refuses to bury the encrypted-QR path."""
    app = build()
    async with app.run_test(size=CONSOLE) as pilot:
        await reach_home(pilot)
        names = [path.name for path in PATHS[:3]]
        assert names == [
            "Generate a new wallet",
            "Type a seed in",
            "Restore from an encrypted wallet QR",
        ]
        for index in range(3):
            widget = app.screen.query_one(f"#path-{index}", Static)
            assert "path-unavailable" not in widget.classes or PATHS[index].needs_camera


NETWORK_PATH = "Choose the network"


async def load_wallet(pilot, app: SignerApp) -> None:
    """Reach a loaded wallet the way the appliance does — through the passphrase screen, which is
    the one tail all three ways in share, and therefore the one place the latch can close."""
    app.begin_passphrase(VECTOR_MNEMONIC)
    await pilot.pause()
    await pilot.press("f10")
    await pilot.pause()


async def test_mainnet_is_the_default_and_costs_no_keypress() -> None:
    """The appliance is written for a stranger booting the ISO with real funds. The default is not
    silent for being free: it is on the header and on the path's own line."""
    app = build()
    async with app.run_test(size=CONSOLE) as pilot:
        await reach_home(pilot)
        assert app.network is Network.MAINNET
        assert CHOOSE_NETWORK in texts(app)
        assert "aobs  ·  mainnet" in texts(app), "the header says which chain the session is on"
        assert f"{NETWORK_PATH}  ·  mainnet" in texts(app), "and so does the path beside it"


async def test_the_network_does_not_move_under_an_arrow_key() -> None:
    """It used to move under left/right, one row from the up/down that selects a path — the only
    setting on the appliance that changed without `F10`."""
    app = build()
    async with app.run_test(size=CONSOLE) as pilot:
        await reach_home(pilot)
        await pilot.press("right", "left", "right")
        await pilot.pause()
        assert app.network is Network.MAINNET


async def test_the_network_is_chosen_through_a_path_and_fixed_for_the_session() -> None:
    app = build()
    async with app.run_test(size=CONSOLE) as pilot:
        await open_path(pilot, app, NETWORK_PATH)
        assert isinstance(app.screen, NetworkScreen)
        assert app.screen.selected_network is Network.MAINNET, "opens on the session's own network"

        await pilot.press("down")
        await pilot.press("f10")
        await pilot.pause()
        assert isinstance(app.screen, HomeScreen), "and lands back where it was opened from"
        assert app.network is Network.TESTNET4
        assert f"{NETWORK_PATH}  ·  testnet4" in texts(app)
        assert not app.network_fixed, "reversible right up until a wallet is made"

        await load_wallet(pilot, app)
        assert app.network_fixed
        assert app.wallet is not None and app.wallet.network is Network.TESTNET4


async def test_the_network_path_closes_for_good_once_a_wallet_is_derived_on_it() -> None:
    """A latch, not a guard on `app.wallet`: the rule the session has is *fixed for the rest of
    the session*, and a later *forget this wallet* path must not quietly re-open it."""
    app = build()
    async with app.run_test(size=CONSOLE) as pilot:
        await reach_home(pilot)
        await load_wallet(pilot, app)
        await pilot.press("f10")  # done, off the fingerprint screen
        await pilot.pause()

        assert NETWORK_FIXED in texts(app)
        index = next(i for i, path in enumerate(PATHS) if path.name == NETWORK_PATH)
        assert "path-unavailable" in app.screen.query_one(f"#path-{index}", Static).classes

        await open_path(pilot, app, NETWORK_PATH)
        assert isinstance(app.screen, HomeScreen), "the accept key on it does nothing at all"

        # And the latch does not re-open even if the wallet itself goes away.
        app.wallet = None
        await open_path(pilot, app, NETWORK_PATH)
        assert isinstance(app.screen, HomeScreen)


async def test_the_fingerprint_screen_names_the_network() -> None:
    """The master fingerprint comes from the seed and is identical on all four networks, so this
    line is the only thing on that screen a wrong-network session would change."""
    app = build()
    async with app.run_test(size=CONSOLE) as pilot:
        await open_path(pilot, app, NETWORK_PATH)
        await pilot.press("down", "down")  # signet
        await pilot.press("f10")
        await pilot.pause()
        await load_wallet(pilot, app)

        assert isinstance(app.screen, FingerprintScreen)
        assert "network  signet  ·  fixed for the rest of this session" in texts(app)

        on_mainnet = Wallet.from_mnemonic(VECTOR_MNEMONIC, network=Network.MAINNET)
        assert app.wallet is not None
        assert app.wallet.fingerprint_hex == on_mainnet.fingerprint_hex, (
            "which is exactly why the line has to be there"
        )


# --- Generation -----------------------------------------------------------------------------------


async def test_generation_offers_dice_first_and_never_asks_a_word_count() -> None:
    app = build()
    async with app.run_test(size=CONSOLE) as pilot:
        await open_path(pilot, app, "Generate a new wallet")
        assert isinstance(app.screen, DiceScreen)
        assert OFFER in texts(app)
        assert OFFER == "Roll dice if you don't trust this machine's random number generator."
        for count in (12, 15, 18, 21, 24):
            assert f"{count} words" not in texts(app), "generation does not ask, it is always 24"

        await pilot.press("f10")
        await pilot.pause()
        assert isinstance(app.screen, RecoveryWordsScreen)
        assert len(GENERATED.split()) == 24


async def test_skipping_the_dice_shows_no_warning_and_no_degraded_state() -> None:
    """`docs/entropy-mixing.md`: the floor is not lowered by a source that did not contribute, so
    nothing on this path may imply the wallet is worse for it."""
    app = build()
    async with app.run_test(size=CONSOLE) as pilot:
        await open_path(pilot, app, "Generate a new wallet")
        rendered = texts(app).lower()
        for word in ("warning", "weak", "insecure", "recommended", "at least", "degraded"):
            assert word not in rendered
        assert "%" not in rendered and "▮" not in rendered, "a bar is a quota with a picture"


async def test_the_dice_screen_counts_rolls_and_bits_and_sets_no_quota() -> None:
    app = build()
    async with app.run_test(size=CONSOLE) as pilot:
        await open_path(pilot, app, "Generate a new wallet")
        assert "rolls: 0" in texts(app)
        await pilot.press("1", "6", "3", "9", "5")  # 9 is not a D6 face
        await pilot.pause()
        assert app.screen.rolls == "1635"
        rendered = texts(app)
        assert "rolls: 4" in rendered
        assert "bits contributed: 10.3" in rendered
        await pilot.press("backspace")
        await pilot.pause()
        assert app.screen.rolls == "163"


async def test_mix_is_called_with_exactly_what_the_screens_collected() -> None:
    """One draw from the port, and the dice string as typed.

    Asserted on the source's recorded calls, so a screen that draws entropy twice or drops the
    rolls fails here rather than producing a wallet nobody can reproduce.
    """
    entropy = FixedEntropySource()
    app = build(entropy=entropy)
    async with app.run_test(size=CONSOLE) as pilot:
        await open_path(pilot, app, "Generate a new wallet")
        await pilot.press("2", "5", "5")
        await pilot.press("f10")
        await pilot.pause()

        assert entropy.calls == [ENTROPY_OUTPUT_BYTES], "one draw, of the size mix() takes"
        expected = bip39.from_entropy(
            mix(FixedEntropySource().random_bytes(ENTROPY_OUTPUT_BYTES), dice_rolls="255").value
        )
        assert texts(app).count(expected.split()[0]) >= 1
        assert isinstance(app.screen, RecoveryWordsScreen)
        # The words on screen are the ones that string mixes to, dice included.
        shown = " ".join(
            str(app.screen.query_one(f"#word-{index}", Static).content).split()[1]
            for index in range(24)
        )
        assert shown == expected


async def test_the_facts_screen_reads_the_same_with_no_rolls_as_with_many() -> None:
    """`docs/seed-entry.md`: 0 rolls renders identically to 99, because the absence of dice is not
    a deficiency to dress up."""
    shapes = []
    for rolls in ("", "1" * 99):
        app = build()
        async with app.run_test(size=CONSOLE) as pilot:
            await open_path(pilot, app, "Generate a new wallet")
            if rolls:
                await pilot.press(*rolls)
            await pilot.press("f10")
            await pilot.pause()
            mnemonic = " ".join(app.screen.words)
            await pilot.press("f10")
            await pilot.pause()
            await type_words(pilot, mnemonic.split())
            await pilot.press("f10")  # read-back accepted
            await pilot.pause()
            await pilot.press("f10")  # empty passphrase
            await pilot.pause()

            assert isinstance(app.screen, FingerprintScreen)
            facts = str(app.screen.query_one("#mixing-facts", Static).content)
            shapes.append(facts)
            assert "score" not in facts and "%" not in facts
            assert RECORD_IT in texts(app), "there is nothing to compare a new wallet against"

    with_none, with_many = shapes
    assert with_none == "system: 32 bytes  ·  dice: 0 rolls"
    assert with_many == "system: 32 bytes  ·  dice: 99 rolls"
    # Same shape, same fields, same order: only the quantities differ, and neither is a verdict.
    assert [part.split(":")[0] for part in with_none.split("  ·  ")] == [
        part.split(":")[0] for part in with_many.split("  ·  ")
    ]


async def test_a_failed_read_back_retries_the_same_words() -> None:
    app = build()
    async with app.run_test(size=CONSOLE) as pilot:
        await open_path(pilot, app, "Generate a new wallet")
        await pilot.press("f10")
        await pilot.pause()
        generated = " ".join(app.screen.words)
        await pilot.press("f10")
        await pilot.pause()
        assert isinstance(app.screen, SeedEntryScreen)

        wrong = list(generated.split())
        wrong[16] = "zoo" if wrong[16] != "zoo" else "zone"
        await type_words(pilot, wrong)
        await pilot.press("f10")
        await pilot.pause()
        assert isinstance(app.screen, SeedEntryScreen), "a failed read-back stays put"
        assert READ_BACK_FAILED in texts(app)
        assert app.wallet is None

        # Back to the words, and they are the same words: nothing was regenerated.
        await pilot.press("escape")
        await pilot.pause()
        assert isinstance(app.screen, RecoveryWordsScreen)
        assert " ".join(app.screen.words) == generated


async def test_a_read_back_needs_every_word() -> None:
    app = build()
    async with app.run_test(size=CONSOLE) as pilot:
        await open_path(pilot, app, "Generate a new wallet")
        await pilot.press("f10")
        await pilot.pause()
        generated = list(app.screen.words)
        await pilot.press("f10")
        await pilot.pause()

        await type_words(pilot, generated[:23])
        await pilot.press("f10")
        await pilot.pause()
        assert isinstance(app.screen, SeedEntryScreen), "23 of 24 is not a read-back"
        assert app.wallet is None

        await type_words(pilot, generated[23:])
        await pilot.press("f10")
        await pilot.pause()
        assert isinstance(app.screen, PassphraseScreen)


# --- Typing a seed in -------------------------------------------------------------------------


async def test_the_word_count_is_asked_before_any_slot_exists() -> None:
    app = build()
    async with app.run_test(size=CONSOLE) as pilot:
        await open_path(pilot, app, "Type a seed in")
        assert isinstance(app.screen, WordCountScreen)
        assert not app.screen.query(WordGrid), "no slot exists until the count is settled"
        assert app.screen.selected_count == 12
        await pilot.press("down", "down", "down", "down")
        await pilot.pause()
        assert app.screen.selected_count == 24
        await pilot.press("f10")
        await pilot.pause()
        assert app.screen.query_one(WordGrid).slots == 24


async def reach_seed_grid(pilot, app: SignerApp, words: int = 12) -> WordGrid:
    await open_path(pilot, app, "Type a seed in")
    for _ in range((words - 12) // 3):
        await pilot.press("down")
    await pilot.press("f10")
    await pilot.pause()
    return app.screen.query_one(WordGrid)


async def test_a_word_resolves_at_four_characters() -> None:
    """2048 distinct 4-prefixes is why this is safe here and forbidden in the export grid."""
    app = build()
    async with app.run_test(size=CONSOLE) as pilot:
        grid = await reach_seed_grid(pilot, app)
        await pilot.press("a", "b", "a", "n")
        await pilot.pause()
        # Resolved and shown, so the user checks it rather than trusting it.
        assert "abandon" in str(app.screen.query_one("#slot-0", Static).content)
        await pilot.press("space")
        await pilot.pause()
        assert grid.words[0] == "abandon"
        assert grid.cursor == 1


async def test_full_word_typing_keeps_working_alongside_the_shortcut() -> None:
    """The four-character rule is a shortcut, not a mode."""
    app = build()
    async with app.run_test(size=CONSOLE) as pilot:
        grid = await reach_seed_grid(pilot, app)
        await type_words_in_full(pilot, VECTOR_MNEMONIC.split())
        assert " ".join(grid.words) == VECTOR_MNEMONIC


#: The 49 words that are a prefix of another word. They cannot be entered by the four-character
#: rule at all — `add` never reaches four characters — so the explicit commit is what makes them
#: enterable, and it is proven on the cases that motivated it rather than on one example.
PREFIX_WORDS = tuple(
    word
    for word in bip39.wordlist()
    if any(other != word and other.startswith(word) for other in bip39.wordlist())
)


def test_the_49_prefix_words_are_the_ones_the_commit_rule_exists_for() -> None:
    assert len(PREFIX_WORDS) == 49
    assert "add" in PREFIX_WORDS and "addict" not in PREFIX_WORDS


@pytest.mark.parametrize("word", PREFIX_WORDS, ids=lambda word: word)
async def test_space_commits_a_prefix_word_as_itself(word: str) -> None:
    """The grid is opened through the app rather than walked to: what is under test is the commit
    rule, and forty-nine walks down the home screen would assert the home screen forty-nine
    times."""
    app = build()
    async with app.run_test(size=CONSOLE) as pilot:
        await pilot.press("f10")  # the keymap picker, on to home
        app.open_seed_grid(12)
        await pilot.pause()
        grid = app.screen.query_one(WordGrid)
        await pilot.press(*word, "space")
        await pilot.pause()
        assert grid.words[0] == word, "auto-resolution would have guessed the longer word"


def _collides(first: str, second: str) -> bool:
    """The collision #41 settled the commit rule on.

    A word longer than four characters still has letters left over once its prefix has resolved,
    and the next word may begin with exactly the letter that would have finished it — so a grid
    that committed at four characters could not tell the `l` that starts `lounge` from the `l`
    that ends `cruel`.
    """
    return len(first) > bip39.BIP39_PREFIX and second[0] == first[bip39.BIP39_PREFIX]


#: The three adjacencies #31 hit in one generated seed. They are instances of the rule below, not
#: an unlucky sample, and they are what the keystroke tests are driven on.
COLLIDING_PAIRS = (("cruel", "lounge"), ("merit", "twelve"), ("gospel", "exchange"))


def test_a_four_character_commit_would_mis_slot_more_than_half_of_all_seeds() -> None:
    """#41's evidence, measured here rather than asserted in prose. The wordlist is frozen, so
    these numbers are facts about BIP39 and will not drift."""
    words = bip39.wordlist()
    starts = Counter(word[0] for word in words)
    colliding = sum(
        starts[word[bip39.BIP39_PREFIX]] for word in words if len(word) > bip39.BIP39_PREFIX
    )
    rate = colliding / len(words) ** 2
    assert round(rate, 4) == 0.0335, "3.35% of ordered word pairs collide"
    # 23 adjacencies in a 24-word seed.
    assert round(1 - (1 - rate) ** 23, 2) == 0.54
    assert all(_collides(first, second) for first, second in COLLIDING_PAIRS)


async def test_four_characters_resolve_for_display_and_commit_nothing() -> None:
    """The whole of #41 in one screen: the cell shows `cruel` so the user can check it, and the
    slot is still empty and the cursor has not moved. Resolution is display; the user commits."""
    app = build()
    async with app.run_test(size=CONSOLE) as pilot:
        grid = await reach_seed_grid(pilot, app)
        await pilot.press("c", "r", "u", "e")
        await pilot.pause()
        assert "cruel" in str(app.screen.query_one("#slot-0", Static).content)
        assert grid.words[0] == "", "a resolved prefix is not yet a committed word"
        assert grid.cursor == 0


@pytest.mark.parametrize("first,second", COLLIDING_PAIRS, ids=lambda pair: pair)
async def test_the_shortcut_survives_a_colliding_adjacency(first: str, second: str) -> None:
    """Four characters, a separator, four characters. Under a four-character auto-commit the
    second word's first letter would have been eaten as the tail of the first."""
    app = build()
    async with app.run_test(size=CONSOLE) as pilot:
        await pilot.press("f10")  # the keymap picker, on to home
        app.open_seed_grid(12)
        await pilot.pause()
        grid = app.screen.query_one(WordGrid)
        await pilot.press(*first[:4], "space", *second[:4], "space")
        await pilot.pause()
        assert grid.words[:2] == (first, second)
        assert grid.cursor == 2


@pytest.mark.parametrize("first,second", COLLIDING_PAIRS, ids=lambda pair: pair)
async def test_a_colliding_adjacency_typed_in_full_lands_in_its_own_slots(
    first: str, second: str
) -> None:
    """The other half of #41: the surplus letters of a full-word typist. They finish the word they
    belong to, because the slot is still open until the separator arrives."""
    app = build()
    async with app.run_test(size=CONSOLE) as pilot:
        await pilot.press("f10")
        app.open_seed_grid(12)
        await pilot.pause()
        grid = app.screen.query_one(WordGrid)
        await pilot.press(*first, "space", *second, "space")
        await pilot.pause()
        assert grid.words[:2] == (first, second)


async def test_numeric_index_entry_is_rejected() -> None:
    """SeedSigner's approach, and it exists for devices with four buttons. This one has a
    keyboard, so a digit is not an entry method here — it is simply not a word character."""
    app = build()
    async with app.run_test(size=CONSOLE) as pilot:
        grid = await reach_seed_grid(pilot, app)
        await pilot.press("1", "8", "6", "3")
        await pilot.pause()
        assert grid.words[0] == "", "1863 is not a way to say a word"
        # The slot's own number is "1"; what must not be there is what was typed.
        assert "863" not in str(app.screen.query_one("#slot-0", Static).content)
        assert grid.cursor == 0


async def test_a_checksum_failure_names_no_word_and_leaves_every_slot_editable() -> None:
    app = build()
    async with app.run_test(size=CONSOLE) as pilot:
        grid = await reach_seed_grid(pilot, app)
        wrong = VECTOR_MNEMONIC.split()
        wrong[-1] = "zoo"  # a real BIP39 word, and the wrong one
        await type_words(pilot, wrong)
        await pilot.press("f10")
        await pilot.pause()

        assert isinstance(app.screen, SeedEntryScreen)
        assert app.wallet is None
        assert CHECKSUM_FAILED in texts(app)
        rendered = texts(app)
        assert "did you mean" not in rendered.lower()
        for index, word in enumerate(wrong):
            assert word in rendered, f"slot {index + 1} is still on screen and still editable"

        # Slot 12 alone is fixed, without retyping the eleven that were right — which is the
        # whole reason this is a grid and not a wizard.
        for _ in range(len(wrong) - 1):
            await pilot.press("left")
        assert grid.cursor == 0, "free navigation reaches any slot"
        for _ in range(len(wrong) - 1):
            await pilot.press("right")
        assert grid.cursor == len(wrong) - 1
        await pilot.press("backspace")
        await pilot.press("a", "b", "o", "u", "space")
        await pilot.press("f10")
        await pilot.pause()
        assert isinstance(app.screen, PassphraseScreen)
        assert grid.words[:11] == tuple(wrong[:11]), "the eleven right ones were never retyped"


async def test_a_typed_seed_becomes_the_session_wallet() -> None:
    app = build()
    async with app.run_test(size=CONSOLE) as pilot:
        await reach_seed_grid(pilot, app)
        await type_words(pilot, VECTOR_MNEMONIC.split())
        await pilot.press("f10")
        await pilot.pause()
        await pilot.press("f10")  # no passphrase
        await pilot.pause()

        assert isinstance(app.screen, FingerprintScreen)
        expected = Wallet.from_mnemonic(VECTOR_MNEMONIC, network=Network.MAINNET)
        assert app.wallet is not None
        assert app.wallet.fingerprint_hex == expected.fingerprint_hex
        assert COMPARE_IT in texts(app), "a restored wallet has a fingerprint to compare"
        assert RECORD_IT not in texts(app)
        assert "#mixing-facts" not in texts(app)


# --- The passphrase ---------------------------------------------------------------------------


async def reach_passphrase(pilot, app: SignerApp) -> PassphraseScreen:
    await reach_seed_grid(pilot, app)
    await type_words(pilot, VECTOR_MNEMONIC.split())
    await pilot.press("f10")
    await pilot.pause()
    assert isinstance(app.screen, PassphraseScreen)
    return app.screen


async def test_the_passphrase_is_masked_by_default_and_counted_always() -> None:
    app = build()
    async with app.run_test(size=CONSOLE) as pilot:
        screen = await reach_passphrase(pilot, app)
        assert EMPTY in texts(app) and "0 characters" in texts(app)

        await pilot.press("h", "u", "n", "t", "e", "r")
        await pilot.pause()
        field = str(screen.query_one("#passphrase-field", Static).content)
        assert field == MASK * 6
        assert "hunter" not in texts(app)
        assert "6 characters" in texts(app)

        await pilot.press("backspace")
        await pilot.pause()
        assert "5 characters" in texts(app)


async def test_the_reveal_key_shows_it_and_the_next_keystroke_hides_it_again() -> None:
    app = build()
    async with app.run_test(size=CONSOLE) as pilot:
        screen = await reach_passphrase(pilot, app)
        await pilot.press("h", "u", "n", "t")
        await pilot.press("f2")
        await pilot.pause()
        assert str(screen.query_one("#passphrase-field", Static).content) == "hunt"

        await pilot.press("e")
        await pilot.pause()
        assert str(screen.query_one("#passphrase-field", Static).content) == MASK * 5


async def test_the_passphrase_is_never_typed_twice_and_is_confirmed_by_fingerprint() -> None:
    app = build()
    async with app.run_test(size=CONSOLE) as pilot:
        await reach_passphrase(pilot, app)
        await pilot.press("T", "R", "E", "Z", "O", "R")
        await pilot.press("f10")
        await pilot.pause()

        # One entry, and the next screen is the fingerprint rather than a second field.
        assert isinstance(app.screen, FingerprintScreen)
        assert not app.screen.query("#passphrase-field")
        expected = Wallet.from_mnemonic(
            VECTOR_MNEMONIC, network=Network.MAINNET, passphrase="TREZOR"
        )
        assert app.wallet is not None
        assert app.wallet.fingerprint_hex == expected.fingerprint_hex
        assert app.wallet.has_passphrase
        assert expected.fingerprint_hex in texts(app)


async def test_a_wallet_made_here_is_told_there_is_nothing_to_compare_against() -> None:
    """Two sentences, and a user reading the wrong one draws exactly the wrong conclusion from the
    same eight hex characters — so they are asserted as distinct text."""
    assert RECORD_IT != COMPARE_IT
    assert "nothing to compare" in RECORD_IT
    assert "Check this fingerprint against the one you recorded" in COMPARE_IT


# --- Restoring from an encrypted wallet QR -----------------------------------------------------


def a_backup() -> tuple[bytes, tuple[str, ...]]:
    """A container over the published vector's entropy, and the password that opens it."""
    entropy = bytes(16)  # `abandon abandon … about` is all-zero entropy, by construction
    exported = export_wallet(entropy, fixed_bytes())
    return exported.container, exported.password.words


async def test_the_export_password_has_eight_fixed_slots() -> None:
    container, _ = a_backup()
    app = build()
    async with app.run_test(size=CONSOLE) as pilot:
        await reach_home(pilot)
        app.open_export_password(container)
        await pilot.pause()
        assert isinstance(app.screen, ExportPasswordScreen)
        assert app.screen.query_one(WordGrid).slots == EXPORT_PASSWORD_WORDS == 8
        assert NOT_IN_THE_QR in texts(app)
        assert "passphrase is not in this QR" in texts(app)


async def test_the_export_grid_has_no_four_character_shortcut() -> None:
    """An **absence**, asserted deliberately.

    `docs/export-password.md` measured it: **5,502 of the EFF large list's 7,776 words are still
    ambiguous at four characters**, against BIP39's zero. Four characters here would resolve to
    whichever of several words the implementation happened to reach first. The seed grid two
    modules over resolves at four and is right to; merging the two breaks this one silently.
    """
    container, words = a_backup()
    long_word = next(word for word in eff.wordlist() if len(word) > 5)
    app = build()
    async with app.run_test(size=CONSOLE) as pilot:
        await reach_home(pilot)
        app.open_export_password(container)
        await pilot.pause()
        grid = app.screen.query_one(WordGrid)

        await pilot.press(*long_word[:4], "space")
        await pilot.pause()
        assert grid.words[0] == "", "four characters resolved nothing, and must not"
        assert grid.cursor == 0, "and the slot did not move on"
        assert "EFF large wordlist" in texts(app)

        await pilot.press(*long_word[4:], "space")
        await pilot.pause()
        assert grid.words[0] == long_word, "the full word does resolve"
        assert words  # the container is a real one; opening it is the test below


async def test_a_word_outside_the_list_is_rejected_in_its_own_slot() -> None:
    container, _ = a_backup()
    app = build()
    async with app.run_test(size=CONSOLE) as pilot:
        await reach_home(pilot)
        app.open_export_password(container)
        await pilot.pause()
        grid = app.screen.query_one(WordGrid)

        await pilot.press("x", "y", "z", "z", "y", "space")
        await pilot.pause()
        assert grid.words[0] == "", "nothing was accepted"
        assert grid.cursor == 0, "and the slot did not move on"
        assert "EFF large wordlist" in texts(app)
        assert app.wallet is None, "nothing was decrypted"


async def test_eight_valid_words_that_are_the_wrong_password_claim_nothing_about_which() -> None:
    container, words = a_backup()
    wrong = list(words)
    wrong[3] = next(word for word in eff.wordlist() if word != wrong[3])
    app = build()
    async with app.run_test(size=CONSOLE) as pilot:
        await reach_home(pilot)
        app.open_export_password(container)
        await pilot.pause()
        await type_words_in_full(pilot, wrong)
        await pilot.press("f10")
        await pilot.pause()

        rendered = texts(app)
        assert WRONG_PASSWORD in rendered
        assert "wrong password" in rendered.lower() and "tampering" in rendered.lower()
        # No claim as to which: the tag cannot tell them apart, and a verifier that could would
        # hand an offline attacker an oracle.
        assert "the password is wrong" not in rendered.lower()
        assert "tampered" not in rendered.lower()
        assert app.wallet is None
        assert isinstance(app.screen, ExportPasswordScreen), "every slot is still editable"


async def test_the_right_eight_words_restore_the_wallet_and_then_ask_for_the_passphrase() -> None:
    container, words = a_backup()
    app = build()
    async with app.run_test(size=CONSOLE) as pilot:
        await reach_home(pilot)
        app.open_export_password(container)
        await pilot.pause()
        await type_words_in_full(pilot, words)
        await pilot.press("f10")
        await pilot.pause()

        assert isinstance(app.screen, PassphraseScreen), "the QR carried no passphrase"
        await pilot.press("f10")
        await pilot.pause()
        expected = Wallet.from_mnemonic(VECTOR_MNEMONIC, network=Network.MAINNET)
        assert app.wallet is not None
        assert app.wallet.fingerprint_hex == expected.fingerprint_hex
        assert COMPARE_IT in texts(app)


# --- Show recovery words --------------------------------------------------------------------------


async def test_recovery_words_are_shown_only_when_asked_for() -> None:
    app = build()
    async with app.run_test(size=CONSOLE) as pilot:
        await reach_seed_grid(pilot, app)
        await type_words(pilot, VECTOR_MNEMONIC.split())
        await pilot.press("f10")
        await pilot.pause()
        await pilot.press("f10")  # no passphrase
        await pilot.pause()
        await pilot.press("f10")  # done with the fingerprint
        await pilot.pause()

        assert isinstance(app.screen, HomeScreen)
        assert "abandon" not in texts(app), "24 words are not on the way to anything"

        await open_path(pilot, app, "Show recovery words")
        assert isinstance(app.screen, RecoveryWordsScreen)
        rendered = texts(app)
        assert "abandon" in rendered and "about" in rendered
        assert "F10" not in rendered, "this screen leads nowhere: it was the whole request"

        await pilot.press("escape")
        await pilot.pause()
        assert isinstance(app.screen, HomeScreen)
