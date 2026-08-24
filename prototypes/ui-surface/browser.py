"""PROTOTYPE — throwaway. Candidate (c): kiosk browser against a localhost Python server.

Generates a single self-contained HTML file from the same fixture the other two stubs
use, then serves it on 127.0.0.1 — which is exactly the arrangement the ticket is
suspicious of: a loopback HTTP server on an appliance whose central claim is that it
has no network stack.

Run:    uv run --python 3.12 --with embit --with segno python browser.py
Build:  uv run ... python browser.py --build-only   (writes index.html, no server)

`space` flips review / QR in the page.
"""

import http.server
import socketserver
import sys
import webbrowser
from pathlib import Path

import fixture as fx

OUT = Path(__file__).parent / "index.html"


def qr_svg():
    rows, size, ver = fx.qr_matrix()
    q = 4
    n = size + q * 2
    parts = []
    for y, row in enumerate(rows):
        x = 0
        while x < size:
            if row[x]:
                run = 1
                while x + run < size and row[x + run]:
                    run += 1
                parts.append(f'<rect x="{x + q}" y="{y + q}" width="{run}" height="1"/>')
                x += run
            else:
                x += 1
    return (
        f'<svg viewBox="0 0 {n} {n}" shape-rendering="crispEdges" '
        f'xmlns="http://www.w3.org/2000/svg" class="qr">'
        f'<rect width="{n}" height="{n}" fill="#fff"/>'
        f'<g fill="#000">{"".join(parts)}</g></svg>'
    ), size, ver


def html():
    r = fx.REVIEW
    svg, size, ver = qr_svg()

    ins = "".join(
        f'<div class="row"><div class="amt">{fx.btc(i["sats"])} <span>BTC</span></div>'
        f'<div class="meta">{i["txid"][:20]}…:{i["vout"]}</div>'
        f'<div class="meta">{i["derivation"]}</div></div>'
        for i in r["inputs"]
    )

    outs = ""
    for o in r["outputs"]:
        change = o["kind"] == "change"
        outs += (
            f'<div class="row">'
            f'<div class="taghead"><span class="tag {"change" if change else "pay"}">'
            f'{"CHANGE" if change else "PAYMENT"}</span>'
            f'<div class="amt big">{fx.btc(o["sats"])} <span>BTC</span></div></div>'
            f'<div class="addr">{o["address"]}</div>'
            + (f'<div class="ok">✓ {o["note"]}</div>' if o["note"] else "")
            + "</div>"
        )

    warns = "".join(f'<div class="warn"><b>!</b><span>{w}</span></div>' for w in r["warnings"])

    return f"""<title>aobs UI surface — kiosk browser</title>
<style>
  :root {{ --bg:#0b0d10; --fg:#e8eaed; --dim:#8b93a1; --accent:#4c8dff;
           --good:#2ea043; --warn:#d29922; --panel:#15181d;
           --mono: ui-monospace, Menlo, "DejaVu Sans Mono", monospace; }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; background:var(--bg); color:var(--fg); min-height:100vh;
          font:400 16px/1.45 Inter, system-ui, Helvetica, sans-serif; }}
  .kiosk {{ max-width:1024px; margin:0 auto; padding:28px 28px 88px; }}
  .banner {{ background:#1c1205; border:1px solid #4a3410; color:#e9c46a;
             font:400 13px/1.4 var(--mono); padding:10px 12px; border-radius:6px;
             margin-bottom:22px; }}
  h1 {{ font-size:28px; margin:0; letter-spacing:-.01em; }}
  .head {{ display:flex; align-items:baseline; justify-content:space-between; gap:16px;
           margin-bottom:24px; }}
  .head .net {{ font:400 13px/1 var(--mono); color:var(--dim); }}
  .cols {{ display:grid; grid-template-columns:1fr 1fr; gap:28px; }}
  @media (max-width:760px) {{ .cols {{ grid-template-columns:1fr; }} }}
  .lab {{ font:700 11px/1 Inter, sans-serif; letter-spacing:.14em; color:var(--accent);
          margin-bottom:12px; }}
  .row {{ padding:12px 0; border-top:1px solid #1e2228; }}
  .amt {{ font:600 20px/1.2 var(--mono); }}
  .amt.big {{ font-size:24px; }}
  .amt span {{ font-size:.6em; color:var(--dim); font-weight:400; }}
  .meta, .addr {{ font:400 13px/1.5 var(--mono); color:var(--dim); word-break:break-all; }}
  .addr {{ color:var(--fg); margin-top:6px; }}
  .ok {{ font:400 12px/1.5 var(--mono); color:var(--good); margin-top:6px; }}
  .taghead {{ display:flex; align-items:center; gap:10px; }}
  .tag {{ font:700 10px/1 Inter, sans-serif; letter-spacing:.1em; padding:5px 7px;
          border-radius:3px; color:#fff; }}
  .tag.change {{ background:var(--good); }}
  .tag.pay {{ background:#a3372f; }}
  .total {{ font:600 17px/1 var(--mono); padding-top:14px; border-top:1px solid #1e2228; }}
  .fee {{ margin-top:26px; font:400 17px/1.4 var(--mono); }}
  .fee span {{ color:var(--dim); font-size:14px; }}
  .warn {{ display:flex; gap:10px; margin-top:16px; background:var(--warn); color:#1b1200;
           padding:10px 12px; border-radius:4px; font-size:14px; }}
  .qrwrap {{ display:flex; flex-direction:column; align-items:center; gap:14px; }}
  .qr {{ width:min(78vmin, 560px); height:auto; background:#fff; padding:0;
         border-radius:4px; image-rendering:pixelated; }}
  .cap {{ font:400 12px/1 var(--mono); color:var(--dim); }}
  #qr {{ display:none; }}
  body.showqr #rev {{ display:none; }}
  body.showqr #qr {{ display:block; }}
  .bar {{ position:fixed; left:0; right:0; bottom:0; background:var(--panel);
          border-top:1px solid #1e2228; padding:10px 16px;
          font:400 12px/1 var(--mono); color:var(--dim);
          display:flex; gap:18px; justify-content:center; }}
  .bar button {{ background:#22262d; color:var(--fg); border:1px solid #2e343d;
                 border-radius:4px; padding:7px 12px; font:inherit; cursor:pointer; }}
</style>
<div class="kiosk">
  <div class="banner">PROTOTYPE (c) — kiosk browser + localhost HTTP server. Throwaway
  code for wayfinder ticket #3. Signet fixture, BIP39 test-vector mnemonic, no live keys.</div>

  <section id="rev">
    <div class="head">
      <h1>Review and sign</h1>
      <div class="net">{r["network"]} · wallet {r["fingerprint"]}</div>
    </div>
    <div class="cols">
      <div>
        <div class="lab">SPENDING</div>
        {ins}
        <div class="total">total {fx.btc(r["spending_total_sats"])} BTC</div>
      </div>
      <div>
        <div class="lab">PAYING</div>
        {outs}
      </div>
    </div>
    <div class="fee">FEE {fx.btc(r["fee_sats"])} BTC
      <span>({fx.sats(r["fee_sats"])} sats · {r["fee_rate"]} · {r["vsize"]} vB)</span></div>
    {warns}
  </section>

  <section id="qr">
    <div class="head"><h1>Scan this</h1><div class="net">signed PSBT · frame 1 of 3</div></div>
    <div class="qrwrap">{svg}
      <div class="cap">QR v{ver} · {size}×{size} modules · SVG at crisp edges</div>
    </div>
  </section>
</div>
<div class="bar">
  <button onclick="document.body.classList.toggle('showqr')">space — review / qr</button>
  <span>prototype: no state, no persistence</span>
</div>
<script>
  addEventListener('keydown', e => {{
    if (e.code === 'Space') {{ e.preventDefault(); document.body.classList.toggle('showqr'); }}
  }});
</script>
"""


if __name__ == "__main__":
    OUT.write_text(html())
    print(f"wrote {OUT} ({OUT.stat().st_size} bytes)")
    if "--build-only" in sys.argv:
        sys.exit(0)

    class H(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *a, **kw):
            super().__init__(*a, directory=str(OUT.parent), **kw)

        def log_message(self, *a):
            pass

    with socketserver.TCPServer(("127.0.0.1", 8731), H) as srv:
        url = "http://127.0.0.1:8731/index.html"
        print(f"serving {url} — ctrl-c to stop")
        webbrowser.open(url)
        srv.serve_forever()
