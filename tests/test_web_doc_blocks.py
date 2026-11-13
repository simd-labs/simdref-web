"""Browser tests for the doc_sources block rendering in the detail pane.

The pane renders GPU doc text from the ordered doc_sources blocks only
when a row carries them, in list order, with the linked PTX group last.
Tabs with no data behind them never show. One Playwright test per
layout rule, run on the committed doc-blocks fixture overlay:

G1: the guide row shows two groups (one cuda-guide with family mark
    plus its own function section, one ptx-isa), group headings carry
    the entry title in parentheses, header links use title as label,
    and doc text never parses as HTML.
G2: the math row shows one Returns row and no METADATA Result chip; the
    math, note and deflist blocks render. An old pair row still renders.
G3: a CUDA row with no data shows no Operands or Perf tab, an x86 row
    with data shows both.
T1: same-URL entries render one header link (first occurrence wins).
T2: header link label uses entry.title when present.
T3: header link label falls back to entry.source when title is absent.
F1: a cuda code block takes the cpp grammar (hljs classes), a text
    block stays plain, the CUDA signature line highlights as cpp
    and an x86 one stays plain.
F2: runs render code, em, strong, a http(s) link and an inline math
    span; a same-site function link searches its name; an entry with
    the parser keys page, signature and signature_runs still renders.
F3: an ordered list renders as ol.
F4: a nested list renders inside its li item.
F5: a note renders as an admonition; the visible text carries ": "
    between the kind label and the body.
F6: a code caption renders above its code block.
F7: a ptx code block tokenizes on the hljs theme classes: opcode
    hljs-keyword, comment hljs-comment, plus label, directive,
    guard and number spans.

Skips when Playwright or its chromium browser are missing. The shared
server and browser fixtures live in conftest.py.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest

pytest.importorskip("playwright.sync_api")
from playwright.sync_api import Error as PlaywrightError, sync_playwright  # noqa: E402

sys.path.insert(0, str(Path(__file__).parent))
from conftest import FIXTURE_SITE_DATA, STATIC_FILES, _free_port, _serve  # noqa: E402

REPO_ROOT = Path(__file__).parent.parent
OVERLAY = Path(__file__).parent / "fixtures" / "doc-blocks"


@pytest.fixture(scope="module")
def browser():
    try:
        pw = sync_playwright().start()
    except Exception as exc:
        pytest.skip(f"playwright unavailable: {exc}")
    try:
        b = pw.chromium.launch(headless=True)
    except PlaywrightError as exc:
        pw.stop()
        pytest.skip(f"chromium not installed for playwright: {exc}")
    try:
        yield b
    finally:
        b.close()
        pw.stop()


@pytest.fixture(scope="module")
def fixture_url(tmp_path_factory):
    """Serve the base fixture site data with the doc-blocks chunk overlay."""
    out = tmp_path_factory.mktemp("doc-blocks-web")
    shutil.copytree(FIXTURE_SITE_DATA, out, dirs_exist_ok=True)
    for chunk in ("detail-chunks", "intrinsic-chunks"):
        shutil.copytree(OVERLAY / chunk, out / chunk, dirs_exist_ok=True)
    for name in STATIC_FILES:
        shutil.copy(REPO_ROOT / "web" / name, out / name)
    port = _free_port()
    with _serve(out, port):
        yield f"http://127.0.0.1:{port}/"


def _open(page, url):
    page.goto(url)
    page.wait_for_function(
        "() => document.body.dataset.phase2 === 'done'", timeout=60_000, polling=100
    )


def _enable_families(page, families):
    """Switch the named ISA families on: the CUDA preset reaches the
    preset-only CUDA and PTX families, the chips cover the rest."""
    page.locator("#isa-toggle").click()
    page.wait_for_selector("#isa-panel:not(.hidden)", timeout=10_000)
    wanted = list(families)
    if "CUDA" in wanted or "PTX" in wanted:
        page.locator("#isa-cuda").click()
        page.wait_for_timeout(200)
        wanted = [f for f in wanted if f not in ("CUDA", "PTX")]
    for family in wanted:
        cb = page.locator(f'#isa-families input[data-family="{family}"]')
        if not cb.is_checked():
            cb.evaluate("el => el.click()")
    page.wait_for_timeout(300)


def _open_row(page, query, key_part, heading):
    page.locator("#query").fill(query)
    page.wait_for_function(
        "part => Array.from(document.querySelectorAll('#results .result'))"
        ".some(e => (e.dataset.key || '').includes(part))",
        arg=key_part,
        timeout=15_000,
        polling=100,
    )
    keys = page.eval_on_selector_all("#results .result", "els => els.map(e => e.dataset.key)")
    match = [k for k in keys if key_part in k]
    assert match, f"no result row matching {key_part!r}: {keys}"
    page.evaluate(
        "key => Array.from(document.querySelectorAll('#results .result'))"
        ".find(r => r.dataset.key === key)?.click()",
        match[0],
    )
    page.wait_for_function(
        "h => (document.querySelector('#detail h2')?.textContent || '').includes(h)",
        arg=heading,
        timeout=15_000,
        polling=100,
    )
    page.wait_for_function(
        "() => document.querySelector('#detail .kv-compact')", timeout=15_000, polling=100
    )
    page.wait_for_function(
        "() => document.querySelector('#detail .detail-tabs')", timeout=15_000, polling=100
    )


def _doc_groups(page):
    return page.eval_on_selector_all(
        "#detail .doc-group",
        "els => els.map(e => ({"
        " head: e.querySelector('.doc-group-head').innerText,"
        " family: !!e.querySelector('.doc-family'),"
        " text: e.innerText }))",
    )


def _header_links(page):
    return page.eval_on_selector_all(
        "#detail .detail-head .kv-links a",
        "els => els.map(e => [e.textContent.trim(), e.getAttribute('href')])",
    )


def test_g1_guide_row_two_groups_with_title_headings(browser, fixture_url):
    """The guide row renders exactly 2 groups: one cuda-guide (family +
    own section) and one ptx-isa. Headings carry the entry title."""
    page = browser.new_page(viewport={"width": 1440, "height": 900})
    try:
        _open(page, fixture_url)
        _enable_families(page, ["CUDA"])
        _open_row(page, "__shfl_sync", "__shfl_sync", "__shfl_sync")
        page.wait_for_selector("#detail .doc-group", timeout=15_000)
        groups = _doc_groups(page)
        assert len(groups) == 2, groups
        # Group 0: cuda-guide, family mark, title in heading.
        assert groups[0]["family"] is True, groups[0]
        assert "Warp Lane Mirroring Routines" in groups[0]["head"], groups[0]
        assert "Example Guide" in groups[0]["head"], groups[0]
        # Group 0 contains both the shared family text and the row's own section.
        assert "These routines exchange values" in groups[0]["text"], groups[0]
        assert "Lane text one." in groups[0]["text"], groups[0]
        # Group 1: ptx-isa, no family mark, title in heading.
        assert groups[1]["family"] is False, groups[1]
        assert "flane.sync.b32" in groups[1]["head"], groups[1]
        assert "Example ISA" in groups[1]["head"], groups[1]
        # PTX group keeps its rubric sections in order.
        subs = page.eval_on_selector_all(
            "#detail .doc-group:last-child .doc-sub", "els => els.map(e => e.textContent)"
        )
        assert subs == [
            "Syntax",
            "Description",
            "Semantics",
            "PTX ISA Notes",
            "Target ISA Notes",
            "Examples",
        ], subs
        # Doc text is text, never markup.
        assert page.eval_on_selector_all("#detail .doc-groups i", "els => els.length") == 0
        # The old dict shape still renders for a row without doc_sources.
        _open_row(page, "__shfl_xor_sync", "__shfl_xor_sync", "__shfl_xor_sync")
        page.wait_for_selector("#detail .desc-section", timeout=15_000)
        heads = page.eval_on_selector_all(
            "#detail .desc-section summary", "els => els.map(e => e.textContent.trim())"
        )
        assert heads, "dict-shape doc_sections rendered no section"
    finally:
        page.close()


def test_g2_math_row_shows_returns_once_without_result_row(browser, fixture_url):
    page = browser.new_page(viewport={"width": 1440, "height": 900})
    try:
        _open(page, fixture_url)
        _enable_families(page, ["CUDA"])
        _open_row(page, "__shfl_up_sync", "__shfl_up_sync", "__shfl_up_sync")
        page.wait_for_selector("#detail .doc-deflist", timeout=15_000)
        names = page.eval_on_selector_all(
            "#detail .doc-deflist dt", "els => els.map(e => e.textContent.trim())"
        )
        assert names.count("Returns") == 1, names
        text = page.eval_on_selector("#detail", "e => e.innerText")
        assert text.count("Returns") == 1, text
        chips = page.eval_on_selector_all(
            "#detail .kv-chip",
            "els => els.map(e => e.querySelector('.kv-chip-k').textContent.trim())",
        )
        assert "Result" not in chips, chips
        kinds = page.eval_on_selector_all(
            "#detail .doc-note-kind", "els => els.map(e => e.textContent.trim())"
        )
        assert kinds == ["See also", "Note"], kinds
        math = page.eval_on_selector("#detail .doc-math", "e => e.textContent")
        assert math == "y = x * (1 - 2 * (srcLane & 1))", math
        # The old pair shape still renders for a row without doc_sources.
        _open_row(page, "__activemask", "__activemask", "__activemask")
        page.wait_for_selector("#detail .desc-section", timeout=15_000)
        heads = page.eval_on_selector_all(
            "#detail .desc-section summary", "els => els.map(e => e.textContent.trim())"
        )
        assert heads[:3] == ["Description", "Return", "Parameters"], heads
    finally:
        page.close()


def _tab_state(page):
    return page.eval_on_selector_all(
        "#detail .detail-tabs button",
        "els => els.filter(b => !b.classList.contains('detail-all')).map(b => ({"
        " label: b.textContent.trim(), hidden: b.hidden,"
        " display: getComputedStyle(b).display, disabled: b.disabled }))",
    )


def test_g3_tabs_render_only_when_the_row_has_data(browser, fixture_url):
    page = browser.new_page(viewport={"width": 1440, "height": 900})
    try:
        _open(page, fixture_url)
        _enable_families(page, ["CUDA", "SSE", "AVX"])
        _open_row(page, "__shfl_sync", "__shfl_sync", "__shfl_sync")
        page.wait_for_selector("#detail .doc-group", timeout=15_000)
        page.wait_for_function(
            "() => Array.from(document.querySelectorAll('#detail .detail-tabs button'))"
            ".some(b => /Perf/.test(b.textContent) && b.hidden)",
            timeout=15_000,
            polling=100,
        )
        state = _tab_state(page)
        hidden = {t["label"] for t in state if t["hidden"]}
        shown = {t["label"] for t in state if not t["hidden"]}
        assert hidden == {"1 Perf", "3 Operands"}, state
        assert shown == {"2 Semantics", "4 Related"}, state
        for t in state:
            if t["hidden"]:
                assert t["display"] == "none", t
        heads = page.eval_on_selector_all(
            "#detail section.section h3", "els => els.map(e => e.textContent.trim())"
        )
        assert not any("Performance" in h or "Operands" in h for h in heads), heads
        assert "No performance data." not in page.eval_on_selector("#detail", "e => e.innerText")
        # An x86 instruction row with data keeps both tabs.
        _open_row(page, "vaddps", "vaddps", "VADDPS")
        page.wait_for_function(
            "() => Array.from(document.querySelectorAll('#detail .detail-tabs button'))"
            ".some(b => /Perf/.test(b.textContent) && !b.hidden)",
            timeout=15_000,
            polling=100,
        )
        state = _tab_state(page)
        shown = {t["label"] for t in state if not t["hidden"]}
        assert shown == {"1 Perf", "2 Semantics", "3 Operands", "4 Related"}, state
        assert page.eval_on_selector_all("#detail #perf-sec", "els => els.length") == 1
    finally:
        page.close()


def test_same_url_gives_one_link(browser, fixture_url):
    """Two doc_sources entries sharing the same URL render one header link.
    The first entry's label wins."""
    page = browser.new_page(viewport={"width": 1440, "height": 900})
    try:
        _open(page, fixture_url)
        _enable_families(page, ["CUDA", "PTX"])
        _open_row(
            page,
            "shfl.sync.b32",
            "ptx:shfl.sync.b32",
            "shfl.sync.b32",
        )
        page.wait_for_selector("#detail .doc-group", timeout=15_000)
        # Two groups render (two entries), but only one header link for PTX URL.
        groups = _doc_groups(page)
        assert len(groups) == 2, groups
        links = _header_links(page)
        ptx_links = [l for l in links if "flane-sync-b32" in (l[1] or "")]
        assert len(ptx_links) == 1, f"expected 1 PTX link, got {ptx_links}"
    finally:
        page.close()


def test_label_uses_title(browser, fixture_url):
    """Header link labels use entry.title when present."""
    page = browser.new_page(viewport={"width": 1440, "height": 900})
    try:
        _open(page, fixture_url)
        _enable_families(page, ["CUDA"])
        _open_row(page, "__shfl_sync", "__shfl_sync", "__shfl_sync")
        page.wait_for_selector("#detail .doc-group", timeout=15_000)
        links = _header_links(page)
        labels = [l[0] for l in links]
        assert "Example Guide" in labels, labels
        assert "Example ISA" in labels, labels
    finally:
        page.close()


def test_falls_back_to_source(browser, fixture_url):
    """When entry.title is absent, the header link label falls back to
    entry.source."""
    page = browser.new_page(viewport={"width": 1440, "height": 900})
    try:
        _open(page, fixture_url)
        _enable_families(page, ["CUDA"])
        _open_row(page, "__shfl_up_sync", "__shfl_up_sync", "__shfl_up_sync")
        page.wait_for_selector("#detail .doc-deflist", timeout=15_000)
        links = _header_links(page)
        labels = [l[0] for l in links]
        assert "cuda-math-api" in labels, labels
    finally:
        page.close()


def test_f1_code_lang_cuda_gets_hljs_classes(browser, fixture_url):
    """A cuda code block takes the cpp grammar. A text block stays
    plain (a ptx block takes the tokenizer spans, F7). The CUDA
    signature line highlights as cpp; an x86 one stays plain."""
    page = browser.new_page(viewport={"width": 1440, "height": 900})
    try:
        _open(page, fixture_url)
        _enable_families(page, ["CUDA", "SSE", "AVX"])
        _open_row(page, "__shfl_sync", "__shfl_sync", "__shfl_sync")
        # The hljs bundle loads lazily from jsDelivr on the first render.
        page.wait_for_function(
            "() => !!document.querySelector('#detail .desc-code code.hljs')",
            timeout=30_000,
            polling=100,
        )
        cuda = page.eval_on_selector(
            "#detail .desc-code code.hljs",
            "e => ({cls: e.className, lang: e.dataset.lang, hl: e.dataset.hl,"
            " spans: e.querySelectorAll('span[class^=\"hljs-\"]').length})",
        )
        assert cuda["lang"] == "cuda", cuda
        assert cuda["hl"] == "cpp", cuda
        assert "language-cpp" in cuda["cls"].split(), cuda
        assert cuda["spans"] > 0, cuda
        plain = page.eval_on_selector_all(
            '#detail .desc-code code[data-lang="text"]',
            "els => els.map(e => ({lang: e.dataset.lang, cls: e.className,"
            " spans: e.querySelectorAll('span[class^=\"hljs-\"]').length}))",
        )
        assert plain, "no plain text code block"
        for p in plain:
            assert p["spans"] == 0 and "hljs" not in p["cls"].split(), p
        sig = page.eval_on_selector(
            "#detail pre.sig code",
            "e => ({cls: e.className, spans: e.querySelectorAll('span[class^=\"hljs-\"]').length})",
        )
        assert "language-cpp" in sig["cls"].split() and sig["spans"] > 0, sig
        # An x86 row keeps a plain signature line.
        _open_row(page, "vaddps", "vaddps", "VADDPS")
        page.wait_for_selector("#detail pre.sig", timeout=15_000)
        assert page.eval_on_selector_all("#detail pre.sig code", "els => els.length") == 0
    finally:
        page.close()


def test_f2_runs_render_inline_elements(browser, fixture_url):
    """Runs render code, em, strong, http(s) links and inline math. A
    same-site function link runs a search for its name. An entry that
    carries the parser keys page, signature and signature_runs still
    renders."""
    page = browser.new_page(viewport={"width": 1440, "height": 900})
    try:
        _open(page, fixture_url)
        _enable_families(page, ["CUDA"])
        _open_row(page, "__shfl_sync", "__shfl_sync", "__shfl_sync")
        page.wait_for_selector("#detail .doc-p", timeout=15_000)
        # The guide entry carries page, signature and signature_runs.
        assert len(_doc_groups(page)) == 2
        runs = page.eval_on_selector(
            "#detail .doc-p",
            "e => ({codes: [...e.querySelectorAll('code')].map(n => n.textContent),"
            " ems: [...e.querySelectorAll('em')].map(n => n.textContent),"
            " links: [...e.querySelectorAll('a.doc-link')].map(n => [n.textContent,"
            " n.getAttribute('href')]),"
            " fn: [...e.querySelectorAll('button.doc-fnlink')].map(n => n.textContent)})",
        )
        assert "32-bit value" in runs["codes"], runs
        assert "lane" in runs["ems"], runs
        assert [
            "warp rules",
            "https://docs.example.test/guide/lane-extensions.html#warp-rules",
        ] in runs["links"], runs
        assert runs["fn"] == ["__fxlane_pick_sync()"], runs
        assert (
            page.eval_on_selector("#detail .doc-note-warning strong", "e => e.textContent")
            == "memory barrier"
        )
        # The same-site function link searches its name.
        page.locator("#detail button.doc-fnlink").click()
        page.wait_for_function(
            "n => document.getElementById('query').value === n",
            arg="__fxlane_pick_sync()",
            timeout=10_000,
            polling=100,
        )
        # Inline math renders its readable text with the TeX as title.
        _open_row(page, "__shfl_up_sync", "__shfl_up_sync", "__shfl_up_sync")
        page.wait_for_selector("#detail .doc-math-inline", timeout=15_000)
        math = page.eval_on_selector("#detail .doc-math-inline", "e => [e.textContent, e.title]")
        assert math[0] == "y = x * (1 - 2 * (srcLane & 1))", math
        assert math[1] == "y = x\\,(1 - 2\\,(s \\& 1))", math
    finally:
        page.close()


def test_f3_ordered_list_renders_as_ol(browser, fixture_url):
    """An ordered list block renders as ol with its items in order."""
    page = browser.new_page(viewport={"width": 1440, "height": 900})
    try:
        _open(page, fixture_url)
        _enable_families(page, ["CUDA"])
        _open_row(page, "__shfl_sync", "__shfl_sync", "__shfl_sync")
        page.wait_for_selector("#detail ol.doc-list", timeout=15_000)
        items = page.eval_on_selector_all(
            "#detail ol.doc-list > li", "els => els.map(e => e.textContent)"
        )
        assert items == [
            "Read the mask.",
            "Pick the source lane with srcLane.",
            "Store the value at the caller lane.",
        ], items
    finally:
        page.close()


def test_f4_nested_list_renders_inside_li(browser, fixture_url):
    """A list item with nested blocks renders the blocks inside its li."""
    page = browser.new_page(viewport={"width": 1440, "height": 900})
    try:
        _open(page, fixture_url)
        _enable_families(page, ["CUDA"])
        _open_row(page, "__shfl_sync", "__shfl_sync", "__shfl_sync")
        page.wait_for_selector("#detail li > ul.doc-list", timeout=15_000)
        nested = page.eval_on_selector_all(
            "#detail li > ul.doc-list > li", "els => els.map(e => e.textContent)"
        )
        assert nested == [
            "Width must be a power of two.",
            "Width must divide the warp size.",
        ], nested
        owner = page.eval_on_selector(
            "#detail li:has(> ul.doc-list)", "e => e.childNodes[0].textContent"
        )
        assert owner == "Width clamps the source lane range.", owner
    finally:
        page.close()


def test_f5_note_kind_label_renders_admonition(browser, fixture_url):
    """A note renders as an admonition: kind class, kind label and a
    body that keeps its runs. The label stays its own element and the
    visible text carries a ": " separator between label and body, the
    same form the TUI prints."""
    page = browser.new_page(viewport={"width": 1440, "height": 900})
    try:
        _open(page, fixture_url)
        _enable_families(page, ["CUDA"])
        _open_row(page, "__shfl_sync", "__shfl_sync", "__shfl_sync")
        page.wait_for_selector("#detail aside.doc-note-warning", timeout=15_000)
        note = page.eval_on_selector(
            "#detail aside.doc-note-warning",
            "e => ({label: e.querySelector('.doc-note-kind').textContent,"
            " body: !!e.querySelector('.doc-note-body'),"
            " text: e.textContent})",
        )
        assert note["label"] == "Warning", note
        assert note["body"] is True, note
        assert note["text"].startswith("Warning: These routines do not imply"), note
    finally:
        page.close()


def test_f6_caption_renders_above_code(browser, fixture_url):
    """Each code caption renders above its code block."""
    page = browser.new_page(viewport={"width": 1440, "height": 900})
    try:
        _open(page, fixture_url)
        _enable_families(page, ["CUDA"])
        _open_row(page, "__shfl_sync", "__shfl_sync", "__shfl_sync")
        page.wait_for_selector("#detail .doc-code-caption", timeout=15_000)
        caps = page.eval_on_selector_all(
            "#detail .doc-code-caption",
            "els => els.map(e => [e.textContent,"
            " e.nextElementSibling && e.nextElementSibling.className])",
        )
        assert caps == [
            ["Synopsis", "desc-code"],
            ["Example: pick from a lane", "desc-code"],
            ["Build", "desc-code"],
            ["Form", "desc-code"],
            ["Example", "desc-code"],
        ], caps
    finally:
        page.close()


def test_f7_ptx_code_block_tokenizes(browser, fixture_url):
    """A ptx code block carries tokenizer spans on the hljs theme
    classes: the opcode as hljs-keyword and a // comment as
    hljs-comment, plus label, directive, guard and number spans."""
    page = browser.new_page(viewport={"width": 1440, "height": 900})
    try:
        _open(page, fixture_url)
        _enable_families(page, ["CUDA", "PTX"])
        _open_row(page, "shfl.sync.b32", "ptx:shfl.sync.b32", "shfl.sync.b32")
        page.wait_for_selector('#detail code[data-lang="ptx"] span.hljs-comment', timeout=15_000)
        blocks = page.eval_on_selector_all(
            '#detail code[data-lang="ptx"]',
            "els => els.map(e => ({cls: e.className, text: e.textContent,"
            " spans: [...e.querySelectorAll('span[class^=\"hljs-\"]')]"
            " .map(s => [s.className, s.textContent])}))",
        )
        assert blocks, "no ptx code block"
        spans = [tuple(s) for b in blocks for s in b["spans"]]
        assert ("hljs-keyword", "flane.sync.b32") in spans, spans
        assert ("hljs-comment", "// pick from a lane") in spans, spans
        assert ("hljs-title", "loop:") in spans, spans
        assert ("hljs-meta", ".reg") in spans, spans
        assert ("hljs-variable", "@!p") in spans, spans
        assert ("hljs-number", "0xffffffff") in spans, spans
        # The plain text survives around the spans.
        texts = [b["text"] for b in blocks]
        assert any("@!p flane.sync.b32 %r1, %r2, %r3, 0xffffffff;" in t for t in texts), texts
        for b in blocks:
            assert "hljs" in b["cls"].split(), b
    finally:
        page.close()
