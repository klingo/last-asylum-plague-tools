import gallery as G
import gui
import match as M


def sprite(group, name, added=1, changed=None):
    return {"id": f"{group}/{name}", "group": group, "name": name, "w": 144, "h": 144, "added": added, "changed": changed,
            "type": "pictures"}


def test_build_data_sorts_counts_groups_and_marks_what_the_webapp_has():
    index = {"meta": {"run": 2, "baseline": 1, "runs": {"1": {"version": "1.0.1"}, "2": {"version": "1.0.2"}}}, "sprites": {s["id"]: s for s in [
        sprite("B", "zeta"), sprite("A", "beta", added=2), sprite("A", "alpha", changed=2)]}}
    matches = {
        "items/gold.png": [{"id": "A/alpha", "dist": 3}],
        "items/far.png": [{"id": "B/zeta", "dist": M.CLOSE + 1}],  # not close enough: not "in the webapp"
    }
    data = G.build_data(index, matches)
    assert data["baseline"] == 1
    assert data["runs"] == {"1": "1.0.1", "2": "1.0.2"}  # `added` / `changed` are runs: this says in which version
    assert data["groups"] == [("A", 2), ("B", 1)]
    assert [s[0] for s in data["sprites"]] == ["A/alpha", "A/beta", "B/zeta"]
    assert data["sprites"][0] == ["A/alpha", "A", "alpha", 144, 144, 1, 2]
    assert data["used"] == {"A/alpha": ["items/gold.png"]}


def test_build_data_counts_the_source_of_a_mapped_image_as_in_the_webapp():
    """A webapp image cropped from a tall poster hashes far from it: the mapping still says where it comes from."""
    index = {"meta": {"run": 1, "runs": {}}, "sprites": {s["id"]: s for s in [sprite("A", "poster"), sprite("A", "other")]}}
    matches = {"events/x.webp": [{"id": "A/poster", "dist": M.CLOSE}]}
    mapping = {"events/x.webp": {"source": "A/poster"}, "events/y.webp": {"source": "A/poster"},
               "events/none.webp": {"source": None}, "events/gone.webp": {"source": "A/gone"}}
    assert G.build_data(index, matches, mapping)["used"] == {"A/poster": ["events/x.webp", "events/y.webp"]}
    mapping["events/x.webp"]["overlay"] = {"source": "A/other"}  # a picture put on top counts too
    assert G.build_data(index, matches, mapping)["used"]["A/other"] == ["events/x.webp"]


def test_build_data_without_a_baseline_counts_from_the_start():
    assert G.build_data({"meta": {"run": 1, "runs": {}}, "sprites": {}}, {})["baseline"] == 0


def test_write_makes_a_page_that_reads_data_js(tmp_path, monkeypatch):
    import state as S
    monkeypatch.setattr(S, "load_index", lambda: {"meta": {"run": 1, "runs": {}}, "sprites": {}})
    page = G.write(tmp_path)
    assert page == tmp_path / "index.html" and '<script src="data.js">' in page.read_text(encoding="utf-8")
    assert (tmp_path / "data.js").read_text(encoding="utf-8").startswith("window.GALLERY = {")


def test_build_command_for_each_button():
    base = [gui.sys.executable, "-u", str(gui.MAIN), "--serial", "127.0.0.1:5555"]
    assert gui.build_command("check") == base + ["check"]
    assert gui.build_command("scan", serial=" 1.2.3.4:5555 ", adb="C:/adb.exe", types=("pictures", "data"), pattern=" icon ") == [
        gui.sys.executable, "-u", str(gui.MAIN), "--serial", "1.2.3.4:5555", "--adb-exe", "C:/adb.exe",
        "scan", "--types", "pictures,data", "--filter", "icon"]
    assert gui.build_command("update") == base + ["update", "--types", "pictures"]
    assert gui.build_command("import", sprite=" G/x ", dest=" items/x ", force=True) == base + ["import", "G/x", "items/x", "--force"]
    assert gui.build_command("sync") == base + ["sync"]  # a preview
    assert gui.build_command("sync", apply=True) == base + ["sync", "--apply"]
    assert gui.build_command("baseline") == base + ["baseline"]


def test_the_page_script_is_valid_javascript(tmp_path):
    """The page is a Python string: a newline escape in it once broke the whole script."""
    import re
    import shutil
    import subprocess

    import pytest

    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    script = tmp_path / "page.js"
    script.write_text(re.search(r"<script>([\s\S]*?)</script>", G.PAGE).group(1), encoding="utf-8")
    result = subprocess.run([node, "--check", str(script)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_the_gallery_lists_only_pictures():
    fx = {**sprite("effects/Fx", "glow"), "type": "effects"}
    index = {"meta": {"run": 1, "baseline": 0, "runs": {}}, "sprites": {s["id"]: s for s in [sprite("A", "old"), sprite("B", "new"), fx]}}
    data = G.build_data(index, {})
    assert [s[0] for s in data["sprites"]] == ["A/old", "B/new"] and data["groups"] == [("A", 1), ("B", 1)]
