"""Address verification: `verify(scanned, wallet) -> AddressCheck`.

The receive-side mirror of the proof rule. A compromised watch-only wallet showing an attacker's
receive address is the exact mirror of the change-address attack, and eye-comparing 42 bech32
characters is the defence `docs/psbt-review-model.md` already judged inadequate. So the machine
answers the question instead of presenting evidence for it.

Three verdicts, deliberately parallel to the three output categories, and one wording rule that
`docs/address-verification.md` calls the most important in the document: **not found, never not
yours.** The two causes — an attacker's address, or a legitimate address past the window — are
indistinguishable to the appliance, so it states what it searched and leaves the interpretation
to the user.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .constants import ADDRESS_PAGE_SIZE, ADDRESS_SEARCH_BLOCK
from .review import DerivedPath
from .wallet import (
    CHANGE_CHAIN,
    RECEIVE_CHAIN,
    Network,
    ScriptType,
    Wallet,
    networks_for_address,
    script_type_from_address,
)


class Verdict(str, Enum):
    PROVEN = "proven"
    NOT_FOUND = "not_found"
    WRONG_NETWORK = "wrong_network"
    #: Not one of the three: the scan did not contain an address this appliance can read at all.
    UNREADABLE = "unreadable"


@dataclass(frozen=True)
class AddressCheck:
    verdict: Verdict
    #: The address as scanned, in full and never truncated. None when nothing parsed.
    address: str | None
    #: Set only on PROVEN. The screens lead with this and de-emphasise the address, exactly as a
    #: proven change output is de-emphasised: eye-verifying what the machine proved trains a
    #: habit with no value.
    proven: DerivedPath | None = None
    #: The window actually searched, inclusive, on both chains. Stated on NOT_FOUND so the user
    #: can see what was and was not covered.
    searched: tuple[int, int] | None = None
    #: The script type the address itself stated, where it stated one.
    script_type: ScriptType | None = None
    #: Which of our networks the address belongs to, on WRONG_NETWORK. `tb1…` is ambiguous
    #: between testnet4 and signet, so this is a set and the appliance does not pretend to know.
    address_networks: frozenset[Network] = frozenset()

    @property
    def offers_deeper_search(self) -> bool:
        """Only a miss can be searched deeper. A wrong-network address could never match at any
        depth, so offering to look further would send the user hunting for nothing."""
        return self.verdict is Verdict.NOT_FOUND


def parse_scanned(scanned: str) -> str | None:
    """The address inside a scan: a bare address, or the address of a `bitcoin:` URI.

    Strict about the address and lenient about everything else. `amount`, `label` and `message`
    are read off and dropped here, and no caller can ask for them — an attacker-chosen string
    placed beside an address the user is deciding to trust is a persuasion channel, and the
    cheapest way to satisfy the escape-injection rule is to never carry the field at all.
    """
    text = scanned.strip()
    if not text:
        return None
    if text.lower().startswith("bitcoin:"):
        text = text[len("bitcoin:") :]
        text = text.split("?", 1)[0]  # the query string, parsed off and discarded
    text = text.strip()
    return text or None


def verify(scanned: str, wallet: Wallet, *, blocks: int = 1) -> AddressCheck:
    """Prove a scanned address, or state that it was not found in what was searched.

    `blocks` is how many 200-address blocks to search on each chain, and it is the *caller's*
    request — the user pressing "search further". Nothing derived from the address itself can
    widen it, which is the same rule as the derivation window: the attacker never chooses it.
    """
    address = parse_scanned(scanned)
    if address is None:
        return AddressCheck(Verdict.UNREADABLE, None)

    address_networks = networks_for_address(address)
    if not address_networks:
        return AddressCheck(Verdict.UNREADABLE, address)
    if wallet.network not in address_networks:
        return AddressCheck(
            Verdict.WRONG_NETWORK,
            address,
            script_type=script_type_from_address(address),
            address_networks=frozenset(address_networks),
        )

    script_type = script_type_from_address(address)
    if script_type is None:
        # A network we know, in a script type we do not derive. Not a miss and not an attack.
        return AddressCheck(Verdict.UNREADABLE, address)

    last = max(1, blocks) * ADDRESS_SEARCH_BLOCK
    normalised = address.lower()
    for chain in (RECEIVE_CHAIN, CHANGE_CHAIN):
        for index in range(0, last + 1):
            if wallet.address(script_type, chain, index).lower() == normalised:
                return AddressCheck(
                    Verdict.PROVEN,
                    address,
                    proven=DerivedPath(
                        script_type=script_type,
                        chain=chain,
                        index=index,
                        path=wallet.path(script_type, chain, index),
                    ),
                    searched=(0, last),
                    script_type=script_type,
                )
    return AddressCheck(
        Verdict.NOT_FOUND,
        address,
        searched=(0, last),
        script_type=script_type,
    )


@dataclass(frozen=True)
class ListedAddress:
    index: int
    address: str
    path: str


def page(
    wallet: Wallet,
    script_type: ScriptType,
    *,
    chain: int = RECEIVE_CHAIN,
    start: int = 0,
    count: int = ADDRESS_PAGE_SIZE,
) -> tuple[ListedAddress, ...]:
    """The browsable list: twenty at a time, jump-to-index by `start`, script type chosen.

    A distinct second purpose to the scan flow — it is the check that the descriptor export
    landed intact, run once at setup, where the human genuinely is doing the comparing.
    """
    if start < 0 or count <= 0:
        raise ValueError("start must be non-negative and count positive")
    return tuple(
        ListedAddress(
            index=index,
            address=wallet.address(script_type, chain, index),
            path=wallet.path(script_type, chain, index),
        )
        for index in range(start, start + count)
    )
