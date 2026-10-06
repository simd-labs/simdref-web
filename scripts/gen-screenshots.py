#!/usr/bin/env python3
"""Regenerate the web-app screenshot used in README.md.

The TUI screenshot lives in the core ``simdref`` repo now (it needs
``simdref.tui``, which this repo does not depend on). This script only
covers the web half: serve this repo's static templates plus a
``simdref export`` site-data bundle, then capture headless Firefox.

    scripts/gen-screenshots.py --site-data /path/to/site-data

Images live on the hidden ``refs/assets/docs`` ref so ``main`` stays
lightweight to clone. After running this script, commit the output there:

    git fetch origin refs/assets/docs
    git switch --detach FETCH_HEAD
    mkdir -p img
    cp /tmp/simdref-web.png img/web.png
    git add img/web.png
    git commit -m "docs: refresh web screenshot"
    git push origin HEAD:refs/assets/docs
    git switch -                        # back to your working branch
"""

from __future__ import annotations

import argparse
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from contextlib import closing, contextmanager
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
STATIC_FILES = ("index.html", "app.js", "style.css", "favicon.svg", "logo.svg")
OUT_DIR = Path("/tmp")


def _free_port() -> int:
    with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@contextmanager
def _serve(directory: Path, port: int):
    proc = subprocess.Popen(
        [sys.executable, "-m", "http.server", str(port)],
        cwd=str(directory),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        # Wait for the server to accept connections.
        for _ in range(40):
            with closing(socket.socket()) as s:
                if s.connect_ex(("127.0.0.1", port)) == 0:
                    break
            time.sleep(0.05)
        yield
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            proc.kill()


def render_web(site_data: Path) -> Path | None:
    """Screenshot the web UI in headless Firefox.

    Firefox's headless screenshot fires immediately after load, so the
    page may capture before the async catalog fetch completes. Accept
    that and rerun if the result looks blank.
    """
    firefox = shutil.which("firefox")
    if not firefox:
        print("firefox not on PATH — skipping web screenshot", file=sys.stderr)
        return None
    with tempfile.TemporaryDirectory() as tmp_dir:
        web_dir = Path(tmp_dir) / "web"
        web_dir.mkdir()
        for name in STATIC_FILES:
            shutil.copy(REPO_ROOT / "web" / name, web_dir / name)
        for item in site_data.iterdir():
            dest = web_dir / item.name
            shutil.copytree(item, dest) if item.is_dir() else shutil.copy(item, dest)
        port = _free_port()
        out = OUT_DIR / "simdref-web.png"
        with _serve(web_dir, port):
            # Warm cache fetches — Firefox screenshots too eagerly.
            for path in (
                "/",
                "/search-index-meta.json.gz",
                "/search-index-instructions.json.gz",
                "/search-index-intrinsics.json.gz",
                "/filter_spec.json.gz",
            ):
                try:
                    urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=5).read()
                except Exception:
                    pass
            subprocess.run(
                [
                    firefox,
                    "--headless",
                    "--window-size=1400,900",
                    f"--screenshot={out}",
                    f"http://127.0.0.1:{port}/#_mm_add_ps",
                ],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
    return out if out.exists() else None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--site-data", type=Path, required=True, help="a `simdref export` site-data bundle directory")
    args = ap.parse_args()
    web_path = render_web(args.site_data)
    if web_path:
        print(f"Web screenshot: {web_path}")
        return 0
    print("Web screenshot skipped — see script header for how to capture manually.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
