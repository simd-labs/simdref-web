# simdref-web

Static site for the simdref search UI: `web/index.html`, `web/app.js`,
`web/style.css`. No build step, no `simdref` (or any Python package)
dependency — the JS reads a JSON site-data bundle produced by
`simdref export` (see the core `simdref` repo) directly over HTTP.

Serve `web/` next to a site-data export (`search-index-*.json`,
`filter_spec.json`, `build_stamp.json`, `detail-chunks/`,
`intrinsic-chunks/`, `latency-index.json`) with any static file server.

## Layout

- `web/` — the static site.
- `tests/` — pytest suite: `test_web_e2e.py` (Playwright, real browser)
  and `test_search_index_js.py` (runs `app.js` in a Node `vm` sandbox).
- `tests/fixtures/site-data/` — a tiny, hand-written site-data fixture (2
  intrinsics, 2 instructions) so the tests need no `simdref export` step.
- `tools/profile_web.py` — cold-load / keystroke profiling harness.
- `scripts/gen-screenshots.py` — regenerates the web screenshot for docs.

The whole-index equivalence checker used to migrate this site off the old
templated export (`verify.py`, `build_trunc_arm.py`, `probe.js`) was one-off
migration evidence, not repo tooling, and is kept outside this repo.

## Development setup

```sh
python3 -m venv .venv
.venv/bin/pip install pytest playwright
.venv/bin/playwright install chromium   # once
.venv/bin/python -m pytest -q
```

The Node-driven test (`test_search_index_js.py`) needs `node` on `PATH`
and skips otherwise. `tests/web_assets/run_search_index_check.mjs` has no
npm dependencies.
