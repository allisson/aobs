"""Every string the receive and export side puts on screen, and not one decision behind it.

`docs/address-verification.md` owns the verdicts; `docs/export-password.md` owns the export
wording. This module is the wording half of both, and — like `aobs/ui/reviewtext.py`, whose
`grouped()` it reuses rather than re-implementing — it derives nothing: it is handed an
`AddressCheck`, a `ListedAddress` or a `Wallet` flag and hands back lines.

It is Textual-free on purpose. The two most consequential strings in the appliance are here —
*not found*, never *not yours*, and the passphrase branch on the export message — and both are
worth asserting with no application at all.

**Addresses are grouped in fours and never elided, exactly as on the review screen, and for the
opposite reason.** There the formatting exists because the user *should not* have to eye-verify
proven change; here the user genuinely is comparing by eye against a watch-only wallet. Same
rule, opposite motives, one implementation — because two would drift and only one of them would
be the one an attacker's vanity prefix has to beat.
"""

from __future__ import annotations

from aobs.core.address import AddressCheck, ListedAddress, Verdict
from aobs.core.wallet import Network, ScriptType, Wallet
from aobs.ui.reviewtext import grouped
from aobs.ui.widgets.failure import Failure

# --- Address verification -----------------------------------------------------------------------

TITLE = "Verify a receive address"

#: Leads the proven screen. The path is the substance; the address below it is de-emphasised.
PROVEN_LEAD = "This address is yours. This appliance derived it from its own keys at:"

#: Under the de-emphasised address. Says why there is nothing here to check by eye.
PROVEN_NOTE = (
    "The comparison has already been made. There is nothing on this screen for you to check "
    "character by character."
)

#: The key that widens the window. Not the accept key: the accept key would mark *search further*
#: as the appliance's recommendation, and `docs/address-verification.md` requires two next steps
#: with no default. `F9` is the appliance's key for a state change that confirms nothing, which is
#: exactly what widening the window is.
SEARCH_FURTHER_KEY = "f9"

#: Two key lines, and the second exists only where a deeper search could ever help. Printing
#: `F9` on a screen where it does nothing teaches pressing keys that do nothing.
KEYS = "esc done  ·  F12 power off"
KEYS_SEARCHABLE = "F9 search further  ·  esc done  ·  F12 power off"


def scanned_address(check: AddressCheck) -> str | None:
    """What was scanned, grouped in fours and never elided. `None` when nothing parsed."""
    return grouped(check.address) if check.address is not None else None


def verdict_failure(check: AddressCheck, network: Network, *, block: int) -> Failure:
    """The three non-proven verdicts, in the one failure shape.

    `block` is the size of one search block, so the *search further* step can say what it would
    cost rather than gesturing at "more".
    """
    if check.verdict is Verdict.NOT_FOUND:
        return _not_found(check, block=block)
    if check.verdict is Verdict.WRONG_NETWORK:
        return _wrong_network(check, network)
    if check.verdict is Verdict.UNREADABLE:
        return _unreadable()
    raise ValueError("PROVEN is not a failure")  # pragma: no cover - guarded by the caller


def _not_found(check: AddressCheck, *, block: int) -> Failure:
    """**The most important wording in the appliance.**

    An attacker's address and a legitimate address past the window are indistinguishable from
    here, so this says what was searched and never what the address is. *Not yours* would report
    a gap-limit miss as an attack, and the user who believes it stops receiving their own money.
    """
    first, last = check.searched or (0, 0)
    return Failure(
        condition="address-not-found",
        happened=(
            f"This address was not found. The appliance searched addresses {first}–{last} on "
            "both the receive and the change chain of this wallet, and none of them is this "
            "address. That is all this appliance can tell you: an address further along the "
            "chain and an address from somewhere else look the same from here."
        ),
        next_steps=(
            f"Search the next {block} addresses on each chain — F9.",
            "Stop here, and check with whoever gave you this address before sending anything "
            "to it.",
        ),
    )


def _wrong_network(check: AddressCheck, network: Network) -> Failure:
    """Not a miss. No search is offered, because no depth would ever reach it."""
    return Failure(
        condition="address-wrong-network",
        happened=(
            f"This is {_network_family(check.address_networks)} address. "
            f"This wallet is {network.value}, so this address could not belong to it at "
            "any index."
        ),
        next_steps=(
            "Ask your wallet for an address on this network, or start a session on the network "
            "this address belongs to.",
        ),
    )


def _unreadable() -> Failure:
    return Failure(
        condition="not-an-address",
        happened=(
            "This QR does not carry a Bitcoin address this appliance can read, so there was "
            "nothing to search for."
        ),
        next_steps=(
            "Check that your wallet is showing a receive address rather than a transaction or a "
            "descriptor.",
        ),
    )


def _network_family(networks: frozenset[Network]) -> str:
    """`tb1…` is ambiguous between testnet4 and signet, so both are named and neither is guessed."""
    names = sorted(network.value for network in networks)
    if not names:  # pragma: no cover - WRONG_NETWORK always carries at least one
        return "a foreign"
    if len(names) == 1:
        return f"a {names[0]}"
    return "a " + " or ".join((", ".join(names[:-1]), names[-1]))


# --- The browsable list -------------------------------------------------------------------------

LIST_TITLE = "Your addresses"

#: The list's second purpose, named on the screen rather than left to be inferred. It is the check
#: that the descriptor export landed intact, and it is run once, at setup, before funds move.
LIST_PURPOSE = (
    "Compare these against the addresses your watch-only wallet shows. If they differ, the "
    "descriptor it holds is not the one this appliance exported — stop and export it again "
    "before receiving anything."
)

LIST_KEYS = (
    "↑↓ page  ·  digits then F10 jump to an index  ·  F9 script type  ·  "
    "esc done  ·  F12 power off"
)

SCRIPT_TYPE_NAMES = {ScriptType.P2WPKH: "BIP84 · bc1q", ScriptType.P2TR: "BIP86 · bc1p"}


def list_header(wallet: Wallet, script_type: ScriptType, *, chain: int) -> str:
    """The path all the rows below share, written once so the rows can be addresses alone."""
    return f"{wallet.account_path(script_type)}/{chain}/*    {SCRIPT_TYPE_NAMES[script_type]}"


def list_row(listed: ListedAddress) -> str:
    """One row: the index, then the full address grouped in fours. Never a middle ellipsis."""
    return f"{listed.index:>3}  {grouped(listed.address)}"


def list_position(start: int, count: int) -> str:
    return f"Showing {start}–{start + count - 1}."


def jump_prompt(digits: str) -> str:
    return f"Jump to index: {digits}_" if digits else ""


# --- Descriptor export --------------------------------------------------------------------------

DESCRIPTOR_TITLE = "Export the descriptor"

DESCRIPTOR_INSTRUCTION = (
    "Show this to your watch-only wallet. It carries this wallet's public key, its derivation "
    "path and its fingerprint — and nothing that can spend."
)

#: Named on screen because the two are separate URs on purpose: Green's ur-c rejects a taproot
#: descriptor, and a combined export would take the BIP84 one down with it.
DESCRIPTOR_NEXT = (
    "When your wallet has read it, use Browse your addresses to check that it derives the same "
    "addresses this appliance does."
)

DESCRIPTOR_KEYS = "F9 script type  ·  esc done  ·  F12 power off"


# --- Encrypted wallet QR export -------------------------------------------------------------------

EXPORT_QR_TITLE = "Encrypted wallet QR"

#: Stated plainly, because a user who does not know a second artifact exists photographs this one
#: and believes they have a backup.
PASSWORD_NOT_HERE = (
    "The eight-word password is not on this screen. Without it this QR is nothing, and with it "
    "this QR is everything — which is why they are never shown together."
)

EXPORT_QR_INSTRUCTION = (
    "Photograph or print this code. Keep it apart from the paper you are about to write the "
    "eight words on."
)

EXPORT_QR_KEYS = "F10 show the password  ·  esc cancel  ·  F12 power off"

PASSWORD_TITLE = "Your export password"

PASSWORD_WRITE_IT_DOWN = (
    "Write these eight words on paper, in this order. Store that paper apart from the QR code. "
    "Each word must be written in full: unlike your seed words, these are not settled by their "
    "first four characters."
)

PASSWORD_KEYS = "F10 type them back  ·  esc back  ·  F12 power off"

#: A re-show leads nowhere. `F10` is deliberately absent: printing a key that does nothing here
#: teaches pressing keys that do nothing, the same rule the review screen's locked line follows.
PASSWORD_AGAIN_KEYS = "esc back  ·  F12 power off"

READ_BACK_TITLE = "Type the eight words back"

READ_BACK_WHY = (
    "This is the only moment a mistranscribed word is cheap to catch. After this, the error "
    "surfaces when the QR is the only copy of the wallet."
)

#: Retries the same password. A fresh one would silently invalidate what the user already wrote.
READ_BACK_WRONG = (
    "That is not the password. Nothing has changed — the same eight words are still the ones to "
    "write down. Press F9 to see them again."
)

SHOW_AGAIN_KEY = "f9"
READ_BACK_KEYS = "F10 done  ·  F9 show the words again  ·  esc back  ·  F12 power off"

DONE_TITLE = "Export complete"

#: **The two highest-consequence strings in the appliance.** They differ because the truth
#: differs, and the appliance knows which case it is in — `Wallet.has_passphrase`. Printing the
#: first to a user in the second situation is a lie that gets people robbed.
WITH_PASSPHRASE = (
    "This QR and these eight words together reconstruct your BIP39 recovery words — not your "
    "wallet. Your passphrase is in neither of them, and nothing here is spendable without it. "
    "You must remember it: nothing on this appliance can recover it."
)
WITHOUT_PASSPHRASE = (
    "This QR and these eight words together ARE your wallet. Anyone who holds both can spend "
    "your funds. This wallet has no passphrase, so keeping the paper apart from the QR is the "
    "only thing protecting them."
)

KEEP_THEM_APART = (
    "Write the words on paper and store that paper apart from the QR code, in a different place."
)

DONE_KEYS = "F9 show the words again  ·  esc done  ·  F12 power off"


def closing_message(wallet: Wallet) -> str:
    """Which of the two truths applies to this wallet. Never a guess and never a default."""
    return WITH_PASSPHRASE if wallet.has_passphrase else WITHOUT_PASSPHRASE
