import json
import subprocess
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import aggregate
import config as C
import corrections
import export
import roster as R
import store
import viewer_server
from test_screens_capture import fetch
from test_weeks_store_aggregate import rows

HERE = Path(__file__).resolve().parent.parent


def two_weeks(directory: Path) -> None:
    for week_id, monday in (("2026-W46", date(2026, 11, 9)), ("2026-W47", date(2026, 11, 16))):
        week = store.new_week(week_id, monday)
        week["meta"] = {"my_alliance": "Mice", "my_tag": "SoIM"}
        read_at = datetime(2026, 12, 1, tzinfo=timezone.utc)
        store.put_day(week, "mon", monday, rows((1, "Ann", 8_000_000)), read_at, True, True)
        store.save(week, directory)


def test_the_site_has_the_page_the_week_list_and_a_table_per_week(tmp_path):
    two_weeks(tmp_path / "data")
    written = export.export_site(tmp_path / "site", tmp_path / "data")
    out = tmp_path / "site"
    assert sorted(p.relative_to(out).as_posix() for p in written) == [
        ".nojekyll",
        "api/week/2026-W46.json",
        "api/week/2026-W47.json",
        "api/weeks.json",
        "index.html",
    ]
    weeks = json.loads((out / "api" / "weeks.json").read_text(encoding="utf-8"))
    assert weeks == ["2026-W47", "2026-W46"]  # newest first
    table = json.loads((out / "api" / "week" / "2026-W47.json").read_text(encoding="utf-8"))
    assert table["players"][0]["name"] == "Ann" and table["players"][0]["total"] == 8_000_000
    assert table == aggregate.week_table(store.load("2026-W47", tmp_path / "data"))
    page = (out / "index.html").read_text(encoding="utf-8")
    assert 'fetch("api/weeks.json")' in page and "api/week/" in page and 'name="robots" content="noindex' in page
    assert "fetch(\"/" not in page  # relative URLs only: the site may live below /<repository>/


def test_an_older_export_is_replaced_and_no_data_gives_an_empty_site(tmp_path):
    out = tmp_path / "site"
    out.mkdir()
    (out / "stale.txt").write_text("old", encoding="utf-8")
    export.export_site(out, tmp_path / "no_data")
    assert not (out / "stale.txt").exists()
    assert json.loads((out / "api" / "weeks.json").read_text(encoding="utf-8")) == []


def test_the_export_applies_the_corrections_and_the_member_lists(tmp_path, monkeypatch):
    fixes = tmp_path / "corrections.json"
    fixes.write_text(json.dumps({"corrections": {"SolM": "SoIM"}, "aliases": {"Ann": "Anna"}}), encoding="utf-8")
    monkeypatch.setattr(C, "CORRECTIONS", fixes)
    roster = R.Roster()
    roster.add(date(2026, 11, 16), datetime(2026, 11, 16, tzinfo=timezone.utc), [{"name": "Zed", "rank": "R4"}], 1)
    R.save(roster, tmp_path / "lists")
    monkeypatch.setattr(C, "ROSTER_DIR", tmp_path / "lists")
    two_weeks(tmp_path / "data")
    export.export_site(tmp_path / "site", tmp_path / "data")
    table = json.loads((tmp_path / "site" / "api" / "week" / "2026-W47.json").read_text(encoding="utf-8"))
    assert sorted(p["name"] for p in table["players"]) == ["Anna", "Zed"]  # the alias, and the member with 0 points
    assert next(p for p in table["players"] if p["name"] == "Zed")["filled"] == ["mon"]
    assert corrections.load(fixes).rename("Ann") == "Anna"


def test_the_page_works_against_the_server_and_the_export_alike(tmp_path):
    two_weeks(tmp_path / "data")
    export.export_site(tmp_path / "site", tmp_path / "data")
    server, url = viewer_server.start(tmp_path / "data")
    try:
        for route in ("api/weeks.json", "api/week/2026-W47.json"):
            served = json.loads(fetch(url + route)[1])
            assert served == json.loads((tmp_path / "site" / route).read_text(encoding="utf-8"))
    finally:
        viewer_server.stop(server)


def test_the_export_runs_without_the_image_and_ocr_packages(tmp_path):
    """The publishing workflow installs nothing: the export must not need OpenCV, NumPy or the OCR."""
    blocker = (
        "import sys, runpy\n"
        f"sys.path.insert(0, {str(HERE)!r})\n"
        "for name in ('cv2', 'numpy', 'rapidocr', 'onnxruntime', 'PIL'):\n"
        "    sys.modules[name] = None\n"
        f"sys.argv = ['export.py', '--out', {str(tmp_path / 'site')!r}]\n"
        f"runpy.run_path({str(HERE / 'export.py')!r}, run_name='__main__')\n"
    )
    done = subprocess.run([sys.executable, "-I", "-c", blocker], capture_output=True, text=True, cwd=HERE)
    assert done.returncode == 0, done.stderr
    assert (tmp_path / "site" / "index.html").exists() and "week(s) written" in done.stdout
