"""Profiles, frame capture and the recorder (no emulator needed)."""

import struct
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import capture as C  # noqa: E402
import game_profile as G  # noqa: E402
import kinds as K  # noqa: E402
import recorder  # noqa: E402
import solver as S  # noqa: E402
import vision as V  # noqa: E402


@pytest.fixture
def halloween():
    """Every test leaves the Halloween profile active, as the other test files expect."""
    yield
    G.activate(G.load("halloween_ball"))


def test_the_halloween_profile_matches_the_tuned_values(halloween):
    p = G.load("halloween_ball")
    assert p.tray_slots == 7 and p.match == 3 and p.scale == 1.0
    G.activate(p)
    assert (V.PITCH_X, V.TILE_W, V.LINE_RUN, V.BLOB) == (101.0, 100, 22, 9)
    assert tuple(V.FACE_FREE) == (213, 217, 247)
    assert (S.TRAY_SIZE, S.MATCH) == (7, 3)
    assert K.DEFAULT_LIBRARY.exists()


def test_activating_another_profile_rescales_and_changes_the_rules(halloween, tmp_path, monkeypatch):
    monkeypatch.setattr(G, "PROFILES", tmp_path)
    q = G.Profile("smaller_cards", pitch=(90.9, 96.0), tile=(90, 95), face_free=(200, 210, 240), tray_slots=5, match=2)
    G.save(q)
    assert G.load("smaller_cards") == q and G.available() == ["smaller_cards"]
    G.activate(q)
    assert V.PITCH_X == 90.9 and V.TILE_W == 90
    assert V.LINE_RUN == round(22 * 0.9) and V.BLOB == round(9 * 0.9)
    assert tuple(V.FACE_FREE) == (200, 210, 240)
    assert (S.TRAY_SIZE, S.MATCH) == (5, 2)
    assert K.DEFAULT_LIBRARY == tmp_path / "smaller_cards" / "kinds_default.npz"


def test_solver_follows_tray_size_and_match_count(halloween, monkeypatch):
    monkeypatch.setattr(S, "TRAY_SIZE", 4)
    monkeypatch.setattr(S, "MATCH", 2)
    # pairs vanish; the tray already holds kind 0 and kind 1 (2 of 4 slots)
    tiles = [S.SnapTile(2), S.SnapTile(2), S.SnapTile(0), S.SnapTile(3)]
    moves = S.recommend(tiles, [0, 1], n_kinds=4, depth=3, seed=0)
    assert moves[0].tile == 2 and moves[0].loss_rate == 0  # the second kind-0 tile completes a pair at once
    assert S.residue_hidden([1, 2, 3]) == [1, 0, 1]


def _screencap(img_rgba: np.ndarray, fmt: int = 1, header: int = 12) -> bytes:
    h, w = img_rgba.shape[:2]
    head = struct.pack("<III", w, h, fmt) + (b"\0\0\0\0" if header == 16 else b"")
    return head + img_rgba.tobytes()


@pytest.mark.parametrize("header", [12, 16])
def test_parse_screencap(header):
    rgba = np.zeros((3, 4, 4), np.uint8)
    rgba[..., 0], rgba[..., 1], rgba[..., 2], rgba[..., 3] = 10, 20, 30, 255  # R, G, B, A
    bgr = C.parse_screencap(_screencap(rgba, header=header))
    assert bgr.shape == (3, 4, 3) and tuple(bgr[0, 0]) == (30, 20, 10)
    bgra = rgba[..., [2, 1, 0, 3]].copy()
    assert tuple(C.parse_screencap(_screencap(bgra, fmt=5))[0, 0]) == (30, 20, 10)
    with pytest.raises(ValueError):
        C.parse_screencap(_screencap(rgba)[:-5])


def test_black_bars_are_cropped():
    img = np.zeros((100, 200, 3), np.uint8)
    img[10:90, 60:140] = 120  # a portrait picture in the middle of a landscape screen
    assert C.content_box(img) == (60, 10, 140, 90)


class FakeSource:
    def __init__(self, frames):
        self.frames = list(frames)

    def grab(self):
        if not self.frames:
            raise KeyboardInterrupt  # the player stops recording
        return self.frames.pop(0)

    def describe(self):
        return "fake"


def test_recorder_keeps_each_settled_board_once(tmp_path):
    def board(v):
        img = np.full((340, 190, 3), 40, np.uint8)
        img[100:200, 50:150] = v
        return img

    a, moving, b, c = board(200), board(120), board(90), board(250)
    frames = recorder.record(FakeSource([a, a, a, moving, b, b, b, b, c, c]), tmp_path, sleep=lambda s: None, on_save=lambda e: None)
    assert [f["file"] for f in frames] == ["000.png", "001.png", "002.png"]  # a, b, c; the moving frame is skipped
    assert (tmp_path / "002.png").exists() and (tmp_path / "game.json").exists()
    assert "change" in frames[1] and frames[1]["size"] == [190, 340]


def test_launcher_buttons_build_the_right_commands():
    import gui

    run = gui.build_command("run", "halloween_ball", serial="127.0.0.1:5555", labels=True, auto_click=True, step=True)
    assert run[3:] == ["--profile", "halloween_ball", "run", "--serial", "127.0.0.1:5555", "--labels", "--auto-click", "--step"]
    assert "--step" not in gui.build_command("run", "p", serial="", auto_click=False, step=True)
    assert gui.build_command("record", "p", serial="")[-2:] == ["--serial", C.DEFAULT_SERIAL]
    assert gui.build_command("analyze", "p", image="a.png", out="b.png")[-5:] == ["--image", "a.png", "--out", "b.png", "--labels"]
    assert "--no-record" not in run and gui.build_command("run", "p", record=False)[-1] == "--no-record"


def test_finds_the_game_inside_an_emulator_window():
    """The overlay must sit exactly on the game: locate a frame shown scaled down inside a window with a toolbar."""
    import cv2

    rng = np.random.default_rng(1)
    frame = cv2.GaussianBlur(rng.integers(0, 255, (480, 270, 3), dtype=np.uint8), (0, 0), 3)
    window = np.full((420, 300, 3), 30, np.uint8)
    shown = cv2.resize(frame, (216, 384), interpolation=cv2.INTER_AREA)  # 80 % size, below a 26 px toolbar
    window[26:410, 40:256] = shown
    score, (x0, y0, x1, y1) = C.find_in(window, frame)
    assert score > 0.9
    assert abs(x0 - 40) <= 2 and abs(y0 - 26) <= 2 and abs((x1 - x0) - 216) <= 3 and abs((y1 - y0) - 384) <= 3


def test_check_adb_reports_success_and_failure(monkeypatch):
    class Works:
        adb = "adb.exe"

        def __init__(self, serial, adb=None):
            pass

        def grab(self):
            return np.zeros((1920, 1080, 3), np.uint8)

    monkeypatch.setattr(C, "AdbCapture", Works)
    ok, msg = C.check_adb("127.0.0.1:5555", board=lambda img: "board says hi")
    assert ok and "1080x1920" in msg and msg.endswith("board says hi")

    def refuses(serial, adb=None):
        raise RuntimeError("adb could not connect")

    monkeypatch.setattr(C, "AdbCapture", refuses)
    ok, msg = C.check_adb("127.0.0.1:5599")
    assert not ok and "Android Debug Bridge" in msg


def test_a_briefly_locked_game_json_does_not_stop_the_recording(tmp_path, monkeypatch):
    """A recording crashed with "OSError: [Errno 22] Invalid argument" when another program held game.json."""
    import os

    real_replace, calls = os.replace, {"n": 0}

    def flaky_replace(src, dst):
        calls["n"] += 1
        if calls["n"] <= 2:
            raise OSError(22, "Invalid argument")
        return real_replace(src, dst)

    monkeypatch.setattr(recorder.os, "replace", flaky_replace)
    monkeypatch.setattr(recorder.time, "sleep", lambda s: None)
    assert recorder.write_json(tmp_path / "game.json", {"frames": [1]})  # third try works
    assert (tmp_path / "game.json").read_text().count("1") >= 1

    monkeypatch.setattr(recorder, "write_json", lambda path, data, tries=6: False)  # never works
    board = np.full((340, 190, 3), 40, np.uint8)
    notes = []
    frames = recorder.record(FakeSource([board, board, board]), tmp_path / "rec", sleep=lambda s: None, on_save=notes.append)
    assert [f["file"] for f in frames] == ["000.png"]  # kept recording, the frame is there
    assert any("could not write" in n.get("note", "") for n in notes)


def test_how_a_recorded_game_ended():
    import dataset as D

    assert D.ending([(20, 2, 9), (18, 3, 8), (17, 7, 8)], 7) == "lost"  # full tray on the last board
    assert D.ending([(5, 3, 1), (2, 0, 0), None], 7) == "won"  # nearly empty board, then the result screen
    assert D.ending([(0, 0, 0)], 7) == "won"
    assert D.ending([(3, 4, 0), (2, 5, 0), (1, 2, 0)], 7) == "won"  # one free tile and its pair in the tray: stopped early
    assert D.ending([(2, 4, 0), (1, 4, 0)], 7) == "cut short"  # 5 left: something still lies hidden
    assert D.ending([(30, 5, 12), (29, 6, 12), None], 7) == "lost"  # 6/7, then "game over" covered the board
    assert D.ending([(30, 2, 12), (28, 3, 11), (27, 4, 11)], 7) == "cut short"  # stopped mid-game
    assert D.ending([(30, 2, 12), None, None], 7) == "cut short"  # left the minigame
    assert D.ending([None, None], 7) == "no board"


def test_data_verdict_counts_complete_games(tmp_path, monkeypatch):
    import shutil

    import dataset as D

    def fake(folder, tray_size=7, tail=3, match=3):
        return D.Recording(folder.name, 40, 40, 300.0, "won" if folder.name.startswith("w") else "cut short")

    monkeypatch.setattr(D, "summarise", fake)
    for name in ("w1", "w2", "c1"):
        (tmp_path / name).mkdir()
    verdict, details = D.report(tmp_path)
    assert verdict.startswith("2 of 5 complete games (+1 cut short") and "record 3 more" in verdict
    assert details.count("\n") == 2 and "w1: 40 boards, 5.0 min, won" in details
    for i in range(3, 6):
        (tmp_path / f"w{i}").mkdir()
    assert D.report(tmp_path)[0].startswith("5 complete games: enough")
    assert D.report(tmp_path / "missing")[1] == "No recordings yet."
    monkeypatch.undo()
    board = Path(__file__).resolve().parents[1] / "recordings" / "halloween_ball" / "20261030-201811" / "056.png"
    if board.exists():  # a real mid-game board as the last frame: cut short
        rec = tmp_path / "real"
        rec.mkdir()
        shutil.copy(board, rec / "000.png")
        assert D.summarise(rec).ending == "cut short"


def _bare_adb(monkeypatch, results):
    """An AdbCapture without a device: `_run` answers from `results` (bytes, or an exception to raise)."""
    import subprocess

    cap = object.__new__(C.AdbCapture)
    cap.adb, cap.serial, cap.box = "adb", "127.0.0.1:5555", None
    calls = []

    def run(*args, device=True, timeout=15):
        calls.append(args)
        if args[:2] == ("exec-out", "screencap"):
            r = results.pop(0)
            if isinstance(r, Exception):
                raise r
            return r
        return b"connected"

    monkeypatch.setattr(cap, "_run", run)
    return cap, calls, subprocess


def test_a_stalled_screencap_reconnects_and_retries(monkeypatch):
    """A recording crashed when `adb exec-out screencap` hung for 15 s."""
    rgba = np.full((4, 3, 4), 200, np.uint8)
    good = _screencap(rgba)
    import subprocess

    stall = subprocess.TimeoutExpired("adb", 6)
    cap, calls, _ = _bare_adb(monkeypatch, [stall, good])
    img = cap.grab()
    assert img.shape == (4, 3, 3)
    assert ("disconnect", "127.0.0.1:5555") in calls and ("connect", "127.0.0.1:5555") in calls

    cap, calls, _ = _bare_adb(monkeypatch, [stall, RuntimeError("closed"), stall])
    with pytest.raises(C.DeviceUnavailable):
        cap.grab()
    assert ("kill-server",) in calls  # the last attempt restarts adb itself


def test_the_recorder_waits_for_a_silent_device_and_carries_on(tmp_path):
    def board(v):
        img = np.full((340, 190, 3), 40, np.uint8)
        img[100:200, 50:150] = v
        return img

    class Flaky(FakeSource):
        def grab(self):
            frame = super().grab()
            if isinstance(frame, Exception):
                raise frame
            return frame

    silent = C.DeviceUnavailable("no frame")
    a, b = board(200), board(90)
    events = []
    frames = recorder.record(Flaky([a, a, silent, silent, silent, b, b, b]), tmp_path, sleep=lambda s: None,
                             on_save=lambda e: None, on_event=events.append)
    assert [f["file"] for f in frames] == ["000.png", "001.png"]  # both boards, despite the outage
    assert len(events) == 2 and "not responding" in events[0] and "back" in events[1]


def test_new_minigame_profiles_and_their_recordings_folder(halloween, tmp_path, monkeypatch):
    monkeypatch.setattr(G, "PROFILES", tmp_path / "profiles")
    monkeypatch.setattr(G, "HERE", tmp_path)
    G.save(G.Profile("halloween_ball"))
    p = G.create("christmas_tiles")
    assert p.tray_slots == 7 and p.notes["status"].startswith("untrained")
    assert G.available() == ["christmas_tiles", "halloween_ball"]
    assert G.recordings_dir("christmas_tiles") == tmp_path / "recordings" / "christmas_tiles"
    for bad in ("", "x y", "../evil", "halloween_ball"):
        with pytest.raises(ValueError):
            G.create(bad)


def test_a_dialog_or_a_refresh_is_the_same_game_another_layout_is_not():
    board = [(100, 200), (300, 200), (500, 200), (200, 400)]
    assert recorder.same_game(board, board)  # a dialog: the board is back as it was
    assert recorder.same_game(board, board[:3])  # one tile tapped meanwhile
    assert not recorder.same_game(board, [(150, 250), (350, 250), (550, 250), (250, 450)])  # another layout
    assert not recorder.same_game([(100, 200)], board + [(600, 600)])  # the last tile of a game, then a full new board


def test_the_advisor_records_each_game_into_its_own_folder(tmp_path):
    def board(v):
        img = np.full((340, 190, 3), 40, np.uint8)
        img[100:200, 50:150] = v
        return img

    rec = recorder.AutoRecorder(tmp_path, "test", {"profile": "p"}, on_event=lambda m: None)
    for img in (board(200), board(200), board(90), board(90)):
        rec.feed(img)
    rec.new_game()
    for img in (board(250), board(250)):
        rec.feed(img)
    rec.close()
    folders = sorted(tmp_path.iterdir())
    assert len(folders) == 2
    assert sorted(p.name for p in folders[0].glob("*.png")) == ["000.png", "001.png"]
    assert sorted(p.name for p in folders[1].glob("*.png")) == ["000.png"]
    assert (folders[1] / "game.json").exists()
    rec.close()  # closing twice is harmless
