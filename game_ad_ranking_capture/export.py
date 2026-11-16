"""The viewer as a static site (for GitHub Pages): `python export.py [--out DIR]`, default `site/`.

Writes `index.html` (the viewer's page) and the files the page fetches, `api/weeks.json` (newest first) and
`api/week/<year>-W<week>.json` (one table per week, from `aggregate.week_table`, with `corrections.json` and the member
lists applied), plus `.nojekyll`. These are the same routes the local server answers, so the page is the same in both
places, and it fetches them with relative URLs, so it also works below `/<repository>/`.

Standard library and the table modules only (no OpenCV, no OCR): the publishing workflow runs it without installing
anything. The tables hold the player names of both alliances; the page asks search engines not to index it, which is a
request and no protection.
"""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

import aggregate
import config as C
import store


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, separators=(",", ":")), encoding="utf-8", newline="\n")


def export_site(out: Path, data_dir: Path | None = None, viewer_dir: Path | None = None) -> list[Path]:
    """Writes the static site into `out` (an older export there is replaced); returns what was written."""
    data_dir, viewer_dir = data_dir or C.DATA_DIR, viewer_dir or C.VIEWER_DIR
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    written = [out / "index.html", out / ".nojekyll", out / "api" / "weeks.json"]
    shutil.copyfile(viewer_dir / "index.html", written[0])
    written[1].write_text("", encoding="utf-8")  # no Jekyll processing of the files
    weeks = list(reversed(store.list_weeks(data_dir)))
    write_json(written[2], weeks)
    for week in weeks:
        path = out / "api" / "week" / f"{week}.json"
        write_json(path, aggregate.week_table(store.load(week, data_dir)))
        written.append(path)
    return written


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", type=Path, default=C.HERE / "site", help="the folder to write (replaced if it exists)")
    args = parser.parse_args()
    written = export_site(args.out)
    print(f"{len(written) - 3} week(s) written to {args.out} ({len(written)} files).")


if __name__ == "__main__":
    main()
