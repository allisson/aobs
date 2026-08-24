"""PROTOTYPE — throwaway. Candidate (b): native toolkit, Qt6 via PySide6.

Qt stands in for the whole (b) branch here. GTK4 on macOS would have told us about
Homebrew, not about the appliance; the fork being decided is "native toolkit or not".

Run:  uv run --python 3.12 --with embit --with segno --with pyside6 python qt_pyside.py

`space` flips review / QR, `q` quits. Window is 1024x768 — the resolution floor the
appliance is likely to assume.

Screenshot mode (no display needed):
  QT_QPA_PLATFORM=offscreen uv run ... python qt_pyside.py --shot out
"""

import sys

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QFont, QPainter, QPalette
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

import fixture as fx

BG = "#0b0d10"
FG = "#e8eaed"
DIM = "#8b93a1"
ACCENT = "#4c8dff"
GOOD = "#2ea043"
WARN = "#d29922"
MONO = "Menlo, DejaVu Sans Mono, monospace"


def lbl(text, size=14, color=FG, mono=False, bold=False, wrap=False):
    w = QLabel(text)
    w.setStyleSheet(
        f"color:{color}; font-size:{size}px;"
        f"font-family:{MONO if mono else 'Inter, Helvetica, sans-serif'};"
        f"font-weight:{700 if bold else 400};"
    )
    w.setWordWrap(wrap)
    return w


class QRWidget(QWidget):
    """The QR painted as real pixels — the thing a TUI cannot do."""

    def __init__(self):
        super().__init__()
        self.rows, self.size, self.ver = fx.qr_matrix()
        self.quiet = 4

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        n = self.size + self.quiet * 2
        side = min(self.width(), self.height())
        scale = max(1, side // n)  # integer module size: never a half-pixel module
        span = scale * n
        ox = (self.width() - span) // 2
        oy = (self.height() - span) // 2
        p.fillRect(ox, oy, span, span, QColor("white"))
        p.setBrush(QColor("black"))
        p.setPen(Qt.PenStyle.NoPen)
        for y, row in enumerate(self.rows):
            for x, dark in enumerate(row):
                if dark:
                    p.drawRect(
                        ox + (x + self.quiet) * scale,
                        oy + (y + self.quiet) * scale,
                        scale,
                        scale,
                    )
        p.end()


def review_page():
    r = fx.REVIEW
    page = QWidget()
    v = QVBoxLayout(page)
    v.setContentsMargins(28, 22, 28, 22)
    v.setSpacing(14)

    head = QHBoxLayout()
    head.addWidget(lbl("Review and sign", 26, FG, bold=True))
    head.addStretch()
    head.addWidget(lbl(f"{r['network']}  ·  wallet {r['fingerprint']}", 14, DIM, mono=True))
    v.addLayout(head)

    cols = QHBoxLayout()
    cols.setSpacing(28)

    left = QVBoxLayout()
    left.addWidget(lbl("SPENDING", 12, ACCENT, bold=True))
    for i in r["inputs"]:
        left.addWidget(lbl(f"{fx.btc(i['sats'])} BTC", 18, FG, mono=True))
        left.addWidget(lbl(f"{i['txid'][:20]}…:{i['vout']}", 12, DIM, mono=True))
        left.addWidget(lbl(i["derivation"], 12, DIM, mono=True))
        left.addSpacing(10)
    left.addWidget(lbl(f"total  {fx.btc(r['spending_total_sats'])} BTC", 16, FG, mono=True, bold=True))
    left.addStretch()

    right = QVBoxLayout()
    right.addWidget(lbl("PAYING", 12, ACCENT, bold=True))
    for o in r["outputs"]:
        tag = "CHANGE" if o["kind"] == "change" else "PAYMENT"
        tw = lbl(f"  {tag}  ", 11, "#ffffff", bold=True)
        tw.setStyleSheet(
            tw.styleSheet()
            + f"background:{GOOD if o['kind'] == 'change' else '#a3372f'}; border-radius:3px;"
        )
        row = QHBoxLayout()
        row.addWidget(tw)
        row.addWidget(lbl(f"{fx.btc(o['sats'])} BTC", 18, FG, mono=True, bold=True))
        row.addStretch()
        right.addLayout(row)
        right.addWidget(lbl(o["address"], 13, FG, mono=True, wrap=True))
        if o["note"]:
            right.addWidget(lbl(f"✓ {o['note']}", 12, GOOD, mono=True, wrap=True))
        right.addSpacing(12)
    right.addStretch()

    for side in (left, right):
        box = QFrame()
        box.setLayout(side)
        cols.addWidget(box, 1)
    v.addLayout(cols, 1)

    v.addWidget(
        lbl(
            f"FEE  {fx.btc(r['fee_sats'])} BTC   ({fx.sats(r['fee_sats'])} sats · "
            f"{r['fee_rate']} · {r['vsize']} vB)",
            16,
            FG,
            mono=True,
        )
    )
    for w in r["warnings"]:
        wl = lbl(f"  !   {w}", 13, "#1b1200", wrap=True)
        wl.setStyleSheet(wl.styleSheet() + f"background:{WARN}; border-radius:3px; padding:6px;")
        v.addWidget(wl)
    return page


def qr_page():
    page = QWidget()
    v = QVBoxLayout(page)
    v.setContentsMargins(28, 22, 28, 22)
    q = QRWidget()
    v.addWidget(lbl("Scan this", 26, FG, bold=True))
    v.addWidget(lbl("signed PSBT · frame 1 of 3", 14, DIM, mono=True))
    v.addWidget(q, 1)
    v.addWidget(
        lbl(f"QR v{q.ver} · {q.size}×{q.size} modules · painted at integer module scale", 12, DIM, mono=True)
    )
    return page


class Proto(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("PROTOTYPE (b) Qt6 — aobs UI surface")
        self.resize(1024, 768)
        pal = self.palette()
        pal.setColor(QPalette.ColorRole.Window, QColor(BG))
        self.setPalette(pal)
        self.setAutoFillBackground(True)
        self.stack = QStackedWidget()
        self.stack.addWidget(review_page())
        self.stack.addWidget(qr_page())
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.addWidget(self.stack)
        hint = lbl("  space  review / qr      q  quit", 12, DIM, mono=True)
        hint.setStyleSheet(hint.styleSheet() + "background:#15181d; padding:6px;")
        v.addWidget(hint)

    def keyPressEvent(self, e):
        if e.key() == Qt.Key.Key_Space:
            self.stack.setCurrentIndex(1 - self.stack.currentIndex())
        elif e.key() in (Qt.Key.Key_Q, Qt.Key.Key_Escape):
            self.close()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setFont(QFont("Helvetica", 11))
    w = Proto()
    w.show()

    if "--shot" in sys.argv:
        base = sys.argv[sys.argv.index("--shot") + 1]

        def shoot():
            for i, name in ((0, "review"), (1, "qr")):
                w.stack.setCurrentIndex(i)
                app.processEvents()
                w.grab().save(f"{base}_{name}.png")
            app.quit()

        QTimer.singleShot(300, shoot)

    sys.exit(app.exec())
