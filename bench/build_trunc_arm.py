"""Build verify.py arms under --root from a real `simdref export` site-data
bundle: `control` (untouched), `control2` (a byte-identical mirror, the
positive control proving verify.py reports "identical" on real matches,
not just silence) and `trunc` (same bundle with the columnar search-index
arrays cut to half length — a self-consistent but incomplete index).

    bench/build_trunc_arm.py --site-data DIR --root /path/to/arms
"""
from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
STATIC_FILES = ("index.html", "app.js", "style.css", "favicon.svg", "logo.svg")
TRUNCATED = ("search-index-instructions.json", "search-index-intrinsics.json")


def _link_site_data(site_data: Path, dest: Path, skip: tuple[str, ...] = ()) -> None:
    for item in site_data.iterdir():
        if item.name in skip:
            continue
        (dest / item.name).symlink_to(item)


def _link_static(dest: Path) -> None:
    for name in STATIC_FILES:
        (dest / name).symlink_to(REPO_ROOT / "web" / name)


def _truncate(src: Path, dest: Path, keep_frac: float) -> None:
    """Halve every `cols` array and `n`. The lookup tables (isa/arch/perf/...)
    stay untouched: cols values index into them, so surviving rows still
    decode correctly, just fewer of them (see web/app.js decodeInstructions).
    """
    doc = json.loads(src.read_text())
    n = int(doc["n"] * keep_frac)
    doc["n"] = n
    for col, values in doc["cols"].items():
        doc["cols"][col] = values[:n]
    dest.write_text(json.dumps(doc, separators=(",", ":")))
    # No .gz sidecar: fetchJson falls back to the raw file it can see here.


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--site-data", type=Path, required=True, help="a `simdref export` bundle directory")
    ap.add_argument("--root", type=Path, required=True, help="output directory for the arms")
    ap.add_argument("--keep-frac", type=float, default=0.5, help="fraction of rows the trunc arm keeps")
    args = ap.parse_args()

    args.root.mkdir(parents=True, exist_ok=True)
    for arm in ("control", "control2", "trunc"):
        d = args.root / arm
        if d.exists():
            shutil.rmtree(d)
        d.mkdir()
        _link_static(d)

    control, control2, trunc = (args.root / a for a in ("control", "control2", "trunc"))
    _link_site_data(args.site_data, control)
    _link_site_data(args.site_data, control2)
    _link_site_data(args.site_data, trunc, skip=TRUNCATED + tuple(f"{n}.gz" for n in TRUNCATED))
    for name in TRUNCATED:
        _truncate(args.site_data / name, trunc / name, args.keep_frac)

    for arm in ("control", "control2", "trunc"):
        n = sum(1 for _ in (args.root / arm).iterdir())
        print(f"built {arm}: {n} top-level entries")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
