"""Shared harness for browser tests of the static web app.

Assembles the site (fixture data, or a real export via
SIMDREF_WEB_SITE_DATA) plus this repo's web templates, serves it over
http.server, and hands tests a Playwright browser. Skips when Playwright
or chromium are missing so minimal CI stays green.
"""

from __future__ import annotations

import os
import shutil
import socket
import threading
from contextlib import contextmanager
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent
FIXTURE_SITE_DATA = REPO_ROOT / "tests" / "fixtures" / "site-data"
STATIC_FILES = (
    "index.html",
    "app.js",
    "lines.js",
    "data.js",
    "style.css",
    "favicon.svg",
    "logo.svg",
)

# CI points this at a real `simdref export` output (see rebuild-site.yml) so a
# core format change fails here instead of silently shipping a broken site.
SITE_DATA = (
    Path(os.environ["SIMDREF_WEB_SITE_DATA"])
    if "SIMDREF_WEB_SITE_DATA" in os.environ
    else FIXTURE_SITE_DATA
)


def _populate_site(out: Path) -> None:
    """Copy site-data (the committed fixture, or a real export under CI) plus
    this repo's static template files into ``out``, so most local runs need
    no simdref install and no export step."""
    shutil.copytree(SITE_DATA, out, dirs_exist_ok=True)
    for name in STATIC_FILES:
        shutil.copy(REPO_ROOT / "web" / name, out / name)


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class _QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *args, **kwargs):  # silence stderr spam
        pass


@contextmanager
def _serve(directory: Path, port: int):
    handler = lambda *a, **k: _QuietHandler(*a, directory=str(directory), **k)
    httpd = ThreadingHTTPServer(("127.0.0.1", port), handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=2)


@pytest.fixture(scope="module")
def web_dir(tmp_path_factory) -> Path:
    """Assemble the static site into a tmp dir: fixture site-data + templates."""
    out = tmp_path_factory.mktemp("web")
    _populate_site(out)
    return out


@pytest.fixture(scope="module")
def page_url(web_dir: Path):
    port = _free_port()
    with _serve(web_dir, port):
        yield f"http://127.0.0.1:{port}/"


@pytest.fixture(scope="module")
def browser():
    pw_api = pytest.importorskip("playwright.sync_api")
    try:
        pw = pw_api.sync_playwright().start()
    except Exception as exc:
        pytest.skip(f"playwright unavailable: {exc}")
    try:
        b = pw.chromium.launch(headless=True)
    except pw_api.Error as exc:
        pw.stop()
        pytest.skip(f"chromium not installed for playwright: {exc}")
    try:
        yield b
    finally:
        b.close()
        pw.stop()
