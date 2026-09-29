"""Whole-index equivalence checker: per-entry item hash (every field but
``linked_intrinsics``), exact-token postings and every 1..6-char prefix
posting set, fingerprinted from the live search index in a real browser.

Serves --root over plain HTTP (arms live at --root/<arm>/index.html) and
diffs every other arm against the first ("control"). Exit 1 on any mismatch.

    bench/verify.py --root /path/to/arms control control2 trunc

Requires: pip install playwright && playwright install chromium
"""
from __future__ import annotations

import argparse
import socket
import sys
import threading
from contextlib import closing
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from playwright.sync_api import sync_playwright

HERE = Path(__file__).parent

JS = """() => {
  const h = (s) => { let x = 2166136261; for (let i = 0; i < s.length; i++) { x ^= s.charCodeAt(i); x = Math.imul(x, 16777619); } return x >>> 0; };
  const norm = (o) => JSON.stringify(Object.keys(o).filter(k => k !== 'linked_intrinsics').sort().map(k => [k, o[k]]));
  const items = searchEntries.map(e => e.kind + '|' + e.key + '|' + h(norm(e.item)) + '|' + h(JSON.stringify(e.fields)) + '|' + e.title + '|' + e.subtitle);
  const tok = {}; for (const [t, l] of searchTokenIndex) tok[t] = h([...new Set(l)].join(','));
  const pre = {}; const seen = new Set();
  for (const t of searchTokenIndex.keys()) for (let n = 1; n <= Math.min(6, t.length); n++) seen.add(t.slice(0, n));
  for (const p of seen) {
    const l = typeof prefixPostings === 'function' ? prefixPostings(p) : searchPrefixIndex.get(p);
    pre[p] = h([...new Set(l)].join(','));
  }
  return {items, tok, pre};
}"""


def _free_port() -> int:
    with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class _QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *a, **k):
        pass


def dump(browser, base_url, arm):
    ctx = browser.new_context()
    ctx.add_init_script((HERE / "probe.js").read_text())
    pg = ctx.new_page()
    pg.goto(f"{base_url}/{arm}/index.html")
    pg.wait_for_function("window.__readyAllAt !== null", timeout=120_000, polling=50)
    pg.evaluate("() => applyIsaPreset('all')")
    d = pg.evaluate(JS)
    ctx.close()
    return d


def first_diff(a, b):
    if isinstance(a, list):
        for i in range(max(len(a), len(b))):
            x, y = (a[i] if i < len(a) else None), (b[i] if i < len(b) else None)
            if x != y:
                return f"index {i}: control={x!r} arm={y!r} (len {len(a)} vs {len(b)})"
        return None
    for k in sorted(set(a) | set(b)):
        if a.get(k) != b.get(k):
            return f"key {k!r}: control={a.get(k)} arm={b.get(k)} (size {len(a)} vs {len(b)})"
    return None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", type=Path, required=True, help="directory holding one subdir per arm")
    ap.add_argument("arms", nargs="+", help="arm names; the first is the reference")
    args = ap.parse_args()

    port = _free_port()
    handler = lambda *a, **k: _QuietHandler(*a, directory=str(args.root), **k)
    httpd = ThreadingHTTPServer(("127.0.0.1", port), handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{port}"

    bad = 0
    try:
        with sync_playwright() as pw:
            br = pw.chromium.launch(headless=True)
            ref_name, *rest = args.arms
            ref = dump(br, base_url, ref_name)
            print(f"{ref_name}: {len(ref['items'])} entries, {len(ref['tok'])} tokens, {len(ref['pre'])} prefixes")
            checks = 0
            for arm in rest:
                d = dump(br, base_url, arm)
                for part in ("items", "tok", "pre"):
                    diff = first_diff(ref[part], d[part])
                    print(f"{arm:22s} {part:5s} {'MISMATCH ' + diff if diff else 'identical'}")
                    checks += 1
                    bad += diff is not None
            print(f"{checks - bad}/{checks} checks identical to {ref_name}")
            br.close()
    finally:
        httpd.shutdown()
        thread.join(timeout=2)
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
