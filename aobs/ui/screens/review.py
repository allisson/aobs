"""The review screen: the one where a bug loses money.

Three regions — fixed header, scrolling output list, pinned footer — so the totals and the fee can
never be scrolled off (`docs/review-screen.md`). The screen calls `review()` and renders what comes
back; it re-parses nothing, re-categorises nothing and re-computes nothing.

Two mechanisms carry the whole of its safety, and both are absences as much as presences:

**Scroll-to-end gates the confirm**, and `F10 sign` is not printed while it is locked. Printing a
key that does nothing teaches pressing keys that do nothing, so the lock line says what is missing
instead and replaces itself with the full key line the moment the last row renders — at first
paint, if all outputs already fit.

**There is no jump-to-end key.** No `end`, no `home`, no `G`. Scroll-to-end is the whole mechanism
and a one-keystroke bypass of it is the mash-trainer in a hat, so the scroll container is not
focusable and the four scroll keys are bound here, by name. The absence is the decision, and
`tests/test_review_screen.py` pins the absence.
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import Static

from aobs.core.review import Review, review
from aobs.ui import reviewtext
from aobs.ui.screens.confirm import ConfirmScreen

#: How far `PgUp`/`PgDn` move, as a fraction of the visible list. Not a whole page: a page that
#: moves exactly one viewport can step the last partially-visible output straight past the top.
PAGE_FRACTION = 0.9


class ReviewScreen(Screen):
    """A signable `Review`, rendered. A refused one never reaches here — the app shows the
    refusal screen instead, because `Review.signable` alone chooses between the two."""

    BINDINGS = [
        # By line and by page, and nothing else. `end`, `home` and `G` are deliberately unbound
        # everywhere on this screen; the scroll container is not focusable so it cannot supply
        # them either.
        Binding("up", "scroll_lines(-1)", "Up a line"),
        Binding("down", "scroll_lines(1)", "Down a line"),
        Binding("pageup", "scroll_pages(-1)", "Up a page"),
        Binding("pagedown", "scroll_pages(1)", "Down a page"),
        Binding("f10", "sign", "Sign"),
    ]

    DEFAULT_CSS = """
    ReviewScreen #outputs { height: 1fr; scrollbar-size-vertical: 0; }
    ReviewScreen .output { height: auto; margin-bottom: 1; }
    ReviewScreen .output-path { margin-left: 5; }
    ReviewScreen .output-address { margin-left: 5; }
    ReviewScreen .output-address-dim { text-style: dim; }
    ReviewScreen .output-note { margin-left: 5; }
    ReviewScreen .output-warning { text-style: bold; }
    ReviewScreen #footer { height: auto; }
    """

    def __init__(self, psbt_bytes: bytes, reviewed: Review) -> None:
        super().__init__()
        self.psbt_bytes = psbt_bytes
        self.reviewed = reviewed
        #: Sticky once set. `esc` from the confirm returns with the confirm still unlocked, and
        #: scrolling back up is not a reason to make the user re-read nine outputs.
        self.unlocked = False

    # --- layout -------------------------------------------------------------------------------

    def compose(self) -> ComposeResult:
        title, counts = reviewtext.header_lines(self.reviewed)
        with Vertical(id="frame"):
            yield Static(title, id="title")
            yield Static(counts, id="counts")
            yield Static(reviewtext.footer_rule(), id="header-rule")
            with VerticalScroll(id="outputs", can_focus=False, can_focus_children=False):
                for block in reviewtext.output_blocks(self.reviewed):
                    yield from self._output(block)
            with Vertical(id="footer"):
                yield Static(reviewtext.footer_rule(), id="footer-rule")
                for index, line in enumerate(
                    reviewtext.transaction_warning_lines(self.reviewed)
                ):
                    yield Static(line, id=f"transaction-warning-{index}")
                for index, line in enumerate(reviewtext.headline_lines(self.reviewed)):
                    yield Static(line, id=f"headline-{index}")
                fee = reviewtext.fee_line(self.reviewed)
                if fee is not None:
                    yield Static(fee, id="fee")
                yield Static(reviewtext.footer_rule(), id="keys-rule")
                yield Static("", id="lock")
                yield Static(reviewtext.LOCKED_KEYS, id="keys")

    def _output(self, block: reviewtext.OutputBlock) -> ComposeResult:
        with Vertical(classes="output", id=f"output-{block.number}"):
            yield Static(block.heading, classes="output-heading")
            if block.path is not None:
                # Proven change leads with the proof. Inviting someone to eye-verify a string the
                # machine has already proven trains a habit with no value.
                yield Static(block.path, classes="output-path")
            address_classes = "output-address"
            if block.address_dimmed:
                address_classes += " output-address-dim"
            yield Static(block.address, classes=address_classes)
            for index, note in enumerate(block.notes):
                classes = "output-note output-warning" if note.warning else "output-note"
                yield Static(
                    (reviewtext.WARNING_MARK if note.warning else "") + note.text,
                    classes=classes,
                    id=f"output-{block.number}-note-{index}",
                )

    def on_mount(self) -> None:
        # After the first refresh, so the list has a height and the lock can already be open on a
        # transaction whose outputs all fit. A lock that costs something when it protects nothing
        # is a lock users learn to resent.
        self.call_after_refresh(self._settle)

    def _settle(self) -> None:
        self._refresh_footer()

    # --- scrolling ----------------------------------------------------------------------------

    @property
    def _view(self) -> VerticalScroll:
        return self.query_one("#outputs", VerticalScroll)

    def action_scroll_lines(self, lines: int) -> None:
        self._view.scroll_relative(y=lines, animate=False)
        self.call_after_refresh(self._refresh_footer)

    def action_scroll_pages(self, pages: int) -> None:
        height = max(1, int(self._view.container_size.height * PAGE_FRACTION))
        self.action_scroll_lines(pages * height)

    # --- the lock -----------------------------------------------------------------------------

    def _refresh_footer(self) -> None:
        view = self._view
        if view.scroll_offset.y >= view.max_scroll_y:
            self.unlocked = True
        lock = self.query_one("#lock", Static)
        keys = self.query_one("#keys", Static)
        if self.unlocked:
            lock.display = False
            keys.update(reviewtext.UNLOCKED_KEYS)
            return
        lock.display = True
        first, last = self._visible_range()
        lock.update(reviewtext.lock_line(first, last, len(self.reviewed.outputs)))
        keys.update(reviewtext.LOCKED_KEYS)

    def _visible_range(self) -> tuple[int, int]:
        """Which outputs the user can see, as the lock line counts them.

        Read off the list's own layout rather than estimated from a row height: the blocks have
        different heights, because a warning is three lines and a note is one.
        """
        view = self._view
        top = view.scroll_offset.y
        bottom = top + view.container_size.height
        numbers = [
            index + 1
            for index, block in enumerate(view.query(".output"))
            if block.virtual_region.y < bottom
            and block.virtual_region.y + block.virtual_region.height > top
        ]
        if not numbers:
            return 1, len(self.reviewed.outputs)
        return numbers[0], numbers[-1]

    # --- the confirm --------------------------------------------------------------------------

    def action_sign(self) -> None:
        """`F10` says *I am done reading*, and the confirm is where signing is agreed to.

        The two keys are deliberately different, so a user who mashes `F10` twice lands on the
        confirm and stops. While the lock is on, this does nothing at all — and `F10 sign` is not
        printed, so there is no key being taught that does nothing.
        """
        if not self.unlocked:
            return
        self.app.push_screen(ConfirmScreen(self.psbt_bytes, self.reviewed))


def open_review(app, psbt_bytes: bytes) -> None:
    """Review `psbt_bytes` against the session's wallet and show whichever screen applies.

    `Review.signable` alone chooses. It lives beside the screen rather than on the app because
    the choice is a rendering decision, and the app holds no opinion about a PSBT.
    """
    # Deferred: the money path is a cycle at module level — review opens confirm, confirm opens
    # emit or refusal, and a refusal is where a review that never opened lands. The cycle is real
    # rather than accidental, so it is broken at the one call that closes it.
    from aobs.ui.screens.refusal import RefusalScreen

    reviewed = review(psbt_bytes, app.wallet)
    if reviewed.refusal is None:
        app.push_screen(ReviewScreen(psbt_bytes, reviewed))
    else:
        app.push_screen(RefusalScreen(reviewed.refusal))
