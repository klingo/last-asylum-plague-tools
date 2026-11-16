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
    assert data["sprites"][0] == ["A/alpha", "A", "alpha", 144, 144, 1, 2, []]  # no tags
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
    mapping["events/y.webp"]["beside"] = [{"source": "A/other"}]  # so does a picture next to it
    assert G.build_data(index, matches, mapping)["used"]["A/other"] == ["events/x.webp", "events/y.webp"]


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
    assert gui.build_command("scan", serial=" 1.2.3.4:5555 ", adb="C:/adb.exe", types=("pictures", "data", "models")) == [
        gui.sys.executable, "-u", str(gui.MAIN), "--serial", "1.2.3.4:5555", "--adb-exe", "C:/adb.exe",
        "scan", "--types", "pictures,data,models"]
    assert gui.build_command("update") == base + ["update", "--types", "pictures,data"]  # the pictures and the texts are always taken
    assert gui.build_command("import", sprite=" G/x ", dest=" items/x ", force=True) == base + ["import", "G/x", "items/x", "--force"]
    assert gui.build_command("sync") == base + ["sync"]  # a preview
    assert gui.build_command("sync", apply=True) == base + ["sync", "--apply"]
    assert gui.build_command("baseline") == base + ["baseline"]
    assert gui.build_command("texts") == base + ["texts"]
    assert gui.build_command("text-sync") == base + ["text-sync"]  # a preview
    assert gui.build_command("text-sync", apply=True) == base + ["text-sync", "--apply"]


def test_the_page_script_is_valid_javascript(tmp_path):
    """The page is a Python string: a newline escape in it once broke the whole script."""
    import shutil
    import subprocess

    import pytest

    from html_scripts import inline_script

    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    script = tmp_path / "page.js"
    script.write_text(inline_script(G.PAGE), encoding="utf-8")
    result = subprocess.run([node, "--check", str(script)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_the_gallery_lists_only_pictures():
    fx = {**sprite("effects/Fx", "glow"), "type": "effects"}
    index = {"meta": {"run": 1, "baseline": 0, "runs": {}}, "sprites": {s["id"]: s for s in [sprite("A", "old"), sprite("B", "new"), fx]}}
    data = G.build_data(index, {})
    assert [s[0] for s in data["sprites"]] == ["A/old", "B/new"] and data["groups"] == [("A", 1), ("B", 1)]


def test_build_data_gives_every_picture_its_tags():
    index = {"meta": {"run": 1, "runs": {}}, "sprites": {s["id"]: s for s in [sprite("A", "chest"), sprite("A", "plain")]}}
    rows = G.build_data(index, {}, None, {"A/chest": ["gold", "loot"]})["sprites"]
    assert rows[0][7] == ["gold", "loot"] and rows[1][7] == []


def request(server, method, path, body=None, headers=None):
    import http.client
    import json

    conn = http.client.HTTPConnection("127.0.0.1", server.server_port)
    conn.request(method, path, json.dumps(body) if body is not None else None, headers or {})
    response = conn.getresponse()
    text = response.read().decode("utf-8")
    conn.close()
    return response.status, text


def test_the_gallery_server_serves_the_page_and_saves_tag_edits(tmp_path):
    import json

    out = tmp_path / "out"
    out.mkdir()
    (out / "index.html").write_text("<p>page</p>", encoding="utf-8")
    index = {"meta": {"run": 1, "runs": {}}, "sprites": {s["id"]: s for s in [sprite("A", "box"), sprite("A", "key")]}}
    path = tmp_path / "tags.json"
    path.write_text(json.dumps({"A/box": ["box", "old"]}), encoding="utf-8")
    server, url = G.serve(index, out, path)
    try:
        assert url == f"http://127.0.0.1:{server.server_port}/index.html"
        assert request(server, "GET", "/index.html") == (200, "<p>page</p>")
        json_type = {"Content-Type": "application/json"}
        status, text = request(server, "POST", "/tags", {"ids": ["A/box", "A/key"], "add": ["Loot"], "remove": ["box"]}, json_type)
        assert status == 200 and json.loads(text)["tags"] == {"A/box": ["loot", "old"], "A/key": ["loot"]}
        assert json.loads(path.read_text(encoding="utf-8")) == {"A/box": ["loot", "old"], "A/key": ["loot"]}
        data = json.loads(request(server, "GET", "/data.js")[1].removeprefix("window.GALLERY = ").strip().removesuffix(";"))  # a reload shows it
        assert [row[7] for row in data["sprites"]] == [["loot", "old"], ["loot"]]
        import http.client
        conn = http.client.HTTPConnection("127.0.0.1", server.server_port)
        conn.request("GET", "/data.js")
        assert conn.getresponse().getheader("Cache-Control") == "no-store"  # the browser must not keep the old data.js
        conn.close()
    finally:
        G.stop(server)
    import socket
    with socket.socket() as probe:
        assert probe.connect_ex(("127.0.0.1", server.server_port)) != 0  # stopped: the port is closed, not just idle


def test_the_gallery_server_refuses_what_it_should_not_take(tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    (out / "index.html").write_text("page", encoding="utf-8")
    path = tmp_path / "tags.json"
    server, _ = G.serve({"meta": {"run": 1, "runs": {}}, "sprites": {"A/box": sprite("A", "box")}}, out, path)
    try:
        json_type, edit = {"Content-Type": "application/json"}, {"ids": ["A/box"], "add": ["x"]}
        assert request(server, "GET", "/index.html", headers={"Host": "evil.example"})[0] == 403  # another name for this address (DNS rebinding)
        assert request(server, "HEAD", "/index.html", headers={"Host": "evil.example"})[0] == 403
        assert request(server, "POST", "/tags", edit, {**json_type, "Content-Length": "-1"})[0] == 400  # not a read that waits for the end of the stream
        assert request(server, "POST", "/tags", edit, {**json_type, "Host": "evil.example"})[0] == 403
        assert request(server, "POST", "/tags", edit, {"Content-Type": "text/plain"})[0] == 415  # what a web page of another site can send
        assert request(server, "POST", "/elsewhere", edit, json_type)[0] == 404
        assert request(server, "POST", "/tags", {"ids": ["Z/none"], "add": ["x"]}, json_type)[0] == 400  # unknown picture
        assert request(server, "POST", "/tags", {"ids": "A/box"}, json_type)[0] == 400  # not a list
        assert request(server, "POST", "/tags", {"add": ["x"]}, json_type)[0] == 400  # no ids
        assert not path.exists()
        path.write_text("{ not json", encoding="utf-8")  # a tags.json that cannot be read: an error, and the file is left alone
        status, text = request(server, "POST", "/tags", edit, json_type)
        assert status == 400 and "not valid JSON" in text and path.read_text(encoding="utf-8") == "{ not json"
        path.unlink()
        path.mkdir()  # a tags.json that cannot be written: an answer, not a dropped connection
        assert request(server, "POST", "/tags", edit, json_type)[0] == 500
    finally:
        G.stop(server)


def test_start_writes_the_gallery_and_serves_it(tmp_path, monkeypatch):
    index = {"meta": {"run": 1, "runs": {}}, "sprites": {}}
    monkeypatch.setattr(G.S, "load_index", lambda: index)
    server, url = G.start(tmp_path)
    try:
        assert url.endswith("/index.html") and request(server, "GET", "/data.js")[1].startswith("window.GALLERY = {")
    finally:
        G.stop(server)
