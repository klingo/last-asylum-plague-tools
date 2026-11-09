"""Last Asylum: Plague - Mahjong Minigame Helper (tile-matching minigames such as Phantom Treasure of the Halloween
Ball). By default advisory only: it never taps.

Frames and taps go through ADB (BlueStacks: Settings > Advanced > Android Debug Bridge). The overlay finds the
BlueStacks window on screen by itself; keep it visible.

    python main.py run [--labels]                 # live overlay (Ctrl+C in the console to stop)
    python main.py run --auto-click               # also taps the best tile while it is confident (F8 = pause)
    python main.py run --no-record                # without recording the games (recorded by default)
    python main.py record                         # save every settled board while you play (test data)
    python main.py data                           # how many complete games are recorded, and what is still needed
    python main.py evaluate                       # how accurate the tile reading is on the recorded games
    python main.py advice [--every N]             # how often reading errors change the advice (recorded games)
    python main.py train                          # learn the icons from the recorded games
    python main.py analyze --image shot.png --out annotated.png [--labels]
    python gui.py                                 # the same as buttons

Every command takes `--profile NAME` (default: halloween_ball, the game settings in profiles/NAME/), and the device
commands `--serial ADDRESS` (default 127.0.0.1:5555).
"""

from __future__ import annotations

import argparse
import importlib.util
import _thread
import json
import os
import shutil
import signal
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import board as B  # noqa: E402
import capture as C  # noqa: E402
import game_profile as G  # noqa: E402
import kinds as K  # noqa: E402
import solver as S  # noqa: E402
import vision as V  # noqa: E402

RECORDINGS = HERE / "recordings"  # one sub-folder per profile (minigame), then one per game
KIND_FILE = HERE / "kinds.npz"  # set to the active profile's learned library in main()
MOVING_TOO_LONG = 5.0  # s of a moving screen after which the log says why the marks are gone
RECORD_AFTER = 5.0  # s after the board left the screen that the advisor still records (the result screen)


def render(analysis: B.Analysis, labels: bool) -> np.ndarray:
    """Canonical image with the marks and the status line drawn on it (offline output)."""
    out = analysis.frame.image.copy()
    for m in B.build_marks(analysis, labels):
        if m["type"] == "rect":
            cv2.rectangle(out, (m["x0"], m["y0"]), (m["x1"], m["y1"]), m["color"], m["width"])
        else:
            scale, thick = (1.4, 3) if m.get("big") else (0.6, 2)
            cv2.putText(out, m["text"], (m["x"], m["y"]), cv2.FONT_HERSHEY_SIMPLEX, scale, m["color"], thick)
    cv2.rectangle(out, (0, 0), (out.shape[1], 22), (0, 0, 0), -1)
    cv2.putText(out, B.status_line(analysis), (6, 16), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
    return out


def open_adb(args: argparse.Namespace) -> C.AdbCapture | None:
    try:
        return C.AdbCapture(args.serial, args.adb_exe)
    except (RuntimeError, OSError) as e:
        print(f"ADB: {e}")
        print("Is BlueStacks running, with Settings > Advanced > Android Debug Bridge switched on and this address?")
        return None


def cmd_analyze(args: argparse.Namespace) -> int:
    img = cv2.imread(args.image)
    if img is None:
        print(f"cannot read {args.image}")
        return 1
    lib = K.KindLibrary(Path(args.kinds) if args.kinds else None)
    a = B.analyze(img, B.BoardMemory(lib), samples=args.samples, depth=args.depth, seed=0)
    if a is None:
        print("no board found in the image")
        return 1
    print(B.status_line(a))
    tiles = a.frame.tiles
    for place, m in enumerate([m for m in a.moves if tiles[m.tile].free][:3], start=1):
        t = tiles[m.tile]
        print(f"  {place}. tile {B.kind_letter(t.kind)} at ({t.x:.0f},{t.y:.0f}) value {m.value:.1f} "
              f"frees {m.frees} risk {m.loss_rate:.0%}")
    if args.out:
        cv2.imwrite(args.out, render(a, args.labels))
        print("wrote", args.out)
    if args.kinds:
        lib.save()
    return 0


def cmd_record(args: argparse.Namespace) -> int:
    import recorder

    source = open_adb(args)
    if source is None:
        return 1
    out = Path(args.out) if args.out else G.recordings_dir(args.profile) / datetime.now().strftime("%Y%m%d-%H%M%S")
    print(f"recording {source.describe()} to {out}; play normally, Ctrl+C stops")

    def saved(entry: dict) -> None:
        note = f"  ({entry['note']})" if "note" in entry else ""
        print(f"  {entry['file']}  t={entry['t']:.1f}s{note}", flush=True)

    frames = recorder.record(source, out, extra={"profile": args.profile}, interval=args.interval / 1000, on_save=saved, on_event=lambda m: print("  " + m, flush=True))
    source.close()
    print(f"saved {len(frames)} frames in {out}")
    return 0


def cmd_data(args: argparse.Namespace) -> int:
    import dataset
    import solver as S

    verdict, details = dataset.report(G.recordings_dir(args.profile), S.TRAY_SIZE, S.MATCH)
    print(details)
    print(verdict)
    return 0


def cmd_evaluate(args: argparse.Namespace) -> int:
    import evaluate

    mine = G.recordings_dir(args.profile)
    folders = [Path(f) for f in args.recordings] or (sorted(p for p in mine.iterdir() if p.is_dir() and not p.name.startswith("_")) if mine.exists() else [])
    if not folders:
        print(f"no recordings of {args.profile} yet")
        return 1
    print(f"reading {len(folders)} recordings with the current tool and comparing with what each game revealed...")
    result = evaluate.evaluate(folders, args.profile)
    conf, lines = evaluate.summary(result)
    result["summary"] = {"confidence": round(conf), "lines": lines, "measured": datetime.now().isoformat(timespec="minutes"),
                         "games": len(folders)}
    print(evaluate.report_text(result))
    out = mine / "_evaluation.json"
    out.write_text(json.dumps(result, indent=1), encoding="utf-8")
    print("details:", out)
    return 0


def cmd_advice(args: argparse.Namespace) -> int:
    import advice

    mine = G.recordings_dir(args.profile)
    folders = [Path(f) for f in args.recordings] or (sorted(p for p in mine.iterdir() if p.is_dir() and not p.name.startswith("_"))
                                                     if mine.exists() else [])
    if not folders:
        print(f"no recordings of {args.profile} yet")
        return 1
    print(f"replaying {len(folders)} recordings: the advisor's tap against the tap with perfect recognition...")
    result = advice.check(folders, args.profile, every=args.every, review_dir=mine / "_advice", log=lambda m: print(m, flush=True))
    quality, lines = advice.summary(result)
    result["summary"] = {"quality": round(quality), "lines": lines, "measured": datetime.now().isoformat(timespec="minutes"),
                         "games": len(folders)}
    print(advice.report_text(result))
    out = mine / "_advice.json"
    out.write_text(json.dumps(result, indent=1), encoding="utf-8")
    print("details:", out)
    print("pictures of the worst taps (red = advisor, green = best):", mine / "_advice")
    return 0


def cmd_train(args: argparse.Namespace) -> int:
    import train

    mine = G.recordings_dir(args.profile)
    folders = sorted(p for p in mine.iterdir() if p.is_dir() and not p.name.startswith("_")) if mine.exists() else []
    if not folders:
        print(f"no recordings of {args.profile} yet: record some games first")
        return 1
    train.train(folders, args.profile, log=lambda m: print(m, flush=True))
    print("done: the advisor uses this from its next start. Measure accuracy shows the effect.")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    import hotkeys
    from overlay import BUSY, ERROR, READY, WAIT, Overlay

    B.MAX_RISK = args.max_risk / 100
    if importlib.util.find_spec("numba") is None:
        print(f"numba is missing (needed for the search to the end of the game). Install it with:\n"
              f"  {sys.executable} -m pip install numba", flush=True)
        return 1
    if args.think:
        import solver_fast  # (main() checked that numba is installed)

        print("preparing the search to the end of the game...", flush=True)
        solver_fast.warm_up()  # compiled once after an install, then cached on disk
    C.set_dpi_aware()
    source = open_adb(args)
    if source is None:
        return 1
    found = None
    for attempt in range(15):  # the overlay must sit exactly on the game as BlueStacks shows it
        try:
            found = C.locate_game(source.grab())
        except C.DeviceUnavailable as e:
            print(f"device not responding ({e}), retrying...")
            found = None
        if found:
            break
        if attempt == 0:
            print("looking for the BlueStacks window showing the game (it must be visible, not minimised or covered)...")
        time.sleep(2)
    if not found:
        print("BlueStacks window not found on screen. Bring it to the front and start again.")
        return 1
    hwnd, (gx0, gy0, gx1, gy1) = found
    window_seen = C.window_rect(hwnd)
    screen_scale = V.CANON_W / (gx1 - gx0)  # canonical px per screen px of the game as shown
    print(f"game found on screen at {gx0},{gy0} ({gx1 - gx0}x{gy1 - gy0} px)")
    lib = K.KindLibrary(KIND_FILE)
    memory = B.BoardMemory(lib)
    overlay = Overlay(gx0, gy0, gx1 - gx0, gy1 - gy0)
    last_window_check = time.monotonic()
    prev = analysed = None  # signatures of the previous grab / of the frame last analysed
    last_save = time.monotonic()
    auto = {"on": args.auto_click, "clicks": 0, "awaiting": None, "start": time.monotonic() + 3, "f8": False, "f9": False, "pending": None}
    if args.auto_click:
        print(f"auto-click ON: starts in 3 s, F8 pauses / resumes, at most {args.max_clicks} clicks. Ctrl+C stops.")
    rec = None
    if not args.no_record:
        import recorder

        rec = recorder.AutoRecorder(G.recordings_dir(args.profile), source.describe(), {"profile": args.profile, "by": "advisor"},
                                    on_event=lambda m: print(m, flush=True))
    # recording: a board on screen now?, since when not, and the free tiles of the last board (to tell a new game)
    game = {"board": False, "gone": 0.0, "spots": []}

    view: tuple = ([], "", screen_scale, ("STARTING", BUSY))  # what the overlay currently shows
    said = {"last": "", "moving": None}  # the last log line; since when the board has been moving

    def say(msg: str) -> None:
        """A line in the console (the launcher's log): why the advisor does what it does. Not repeated while the
        reason stays the same."""
        if msg != said["last"]:
            said["last"] = msg
            print(time.strftime("%H:%M:%S ") + msg, flush=True)

    def show(marks: list[dict], status: str, state: tuple[str, str]) -> None:
        """Draw now, even while the script is busy computing (the redraw is forced)."""
        nonlocal view
        view = (marks, status, screen_scale, state)
        overlay.show(*view)
        overlay.root.update()

    def grab() -> np.ndarray:
        return source.grab()

    def follow_window(shot: np.ndarray) -> None:
        """Move the overlay along when the BlueStacks window was moved or resized."""
        nonlocal window_seen, screen_scale, view, last_window_check
        last_window_check = time.monotonic()
        now = C.window_rect(hwnd)
        if now == window_seen:
            return
        moved = C.locate_game(shot)
        if not moved:
            say("the BlueStacks window moved or changed size, but the game was not found in it: the marks may be off. "
                "Keep the window visible (not minimised or covered)")
        if moved:
            window_seen = now
            x0, y0, x1, y1 = moved[1]
            overlay.move(x0, y0, x1 - x0, y1 - y0)
            screen_scale = V.CANON_W / (x1 - x0)
            view = (view[0], view[1], screen_scale, view[3])
            overlay.show(*view)

    def auto_note() -> str:
        if not args.auto_click:
            return ""
        if auto["clicks"] >= args.max_clicks:
            return " | AUTO: click limit reached"
        return f" | AUTO {'ON' if auto['on'] else 'PAUSED (F8)'} {auto['clicks']}"

    def tap(a: B.Analysis) -> bool:
        """Through ADB, in the coordinates of the device frame the analysis was made from."""
        tile = a.frame.tiles[a.moves[0].tile]
        return source.tap(*B.click_point(tile, V.CANON_W / a.frame_width, (0, 0)))

    def maybe_click(a: B.Analysis, analysed_sig: np.ndarray) -> bool:
        """Tap the best tile if auto-click is on and the script is confident. The next ticks see the game react
        (WAITING), settle, and analyse the new board (READY) before anything is clicked again. Returns True when
        the suggestion should be offered again on a later tick (paused, start-up delay, waiting for F9)."""
        nonlocal analysed
        if auto["clicks"] >= args.max_clicks:
            say(f"auto-click stopped: {args.max_clicks} clicks reached (the limit). Start the advisor again to go on")
            return False
        ok, why = B.confidence(a)
        if not ok:
            if " | not clicking" not in view[1]:
                show(view[0], view[1] + f" | not clicking: {why}", view[3])
            best = B.kind_letter(a.frame.tiles[a.moves[0].tile].kind) if a.moves else "-"
            say(f"auto-click waits for you: {why} (best tap: {best}, green 1). Tap yourself or use a booster; "
                "it clicks again by itself on the next safe board")
            return False
        if not auto["on"] or time.monotonic() < auto["start"]:
            if not auto["on"]:
                say("auto-click paused (F8 resumes)")
            return True
        if args.step and not auto["f9"]:
            if "press F9" not in view[1]:
                show(view[0], view[1] + " | press F9 to click", view[3])
            say("press F9 to allow the next click")
            return True
        if C.difference(C.signature(grab()), analysed_sig) > C.CHANGED:  # the board changed while we were thinking
            analysed = None
            return False
        show(view[0], view[1], ("CLICKING", BUSY))
        if not tap(a):  # the device did not take it: offer the same tap again on the next tick
            show(view[0], view[1].split(" | tap")[0] + " | tap did not reach the device, retrying", ("READY", READY))
            say("the tap did not reach the device, retrying")
            return True
        auto["clicks"] += 1
        say(f"click {auto['clicks']}: {B.kind_letter(a.frame.tiles[a.moves[0].tile].kind)}")
        auto["awaiting"], auto["f9"] = time.monotonic(), False
        time.sleep(args.click_delay)
        return False

    def tick() -> None:
        """One look at the device. Nothing that goes wrong in here may stop the advisor: errors are shown and the
        next tick tries again."""
        nonlocal analysed, prev
        try:
            step()
            delay = args.interval
        except KeyboardInterrupt:  # Ctrl+C or the launcher's Stop, mostly while a board is read: end the window's
            say("stopping")  # loop (raising it here would only be printed by tkinter, and the advisor ran on)
            overlay.root.quit()
            return
        except C.DeviceUnavailable as e:
            show([], f"device not responding, retrying ({e})", ("NO DEVICE", ERROR))
            say(f"the device does not respond, retrying every second ({e})")
            delay = 1000
        except Exception as e:  # noqa: BLE001 - keep advising; the next board gets a fresh analysis
            import traceback

            traceback.print_exc()
            show([], f"error: {e} - retrying", ("ERROR", ERROR))
            say(f"error: {e} - retrying")
            analysed = prev = None
            delay = 1000
        overlay.root.after(delay, tick)

    def step() -> None:
        nonlocal prev, analysed, last_save
        shot = grab()
        sig = C.signature(shot)
        stable = prev is not None and C.difference(sig, prev) < C.STABLE  # no tile is flying around
        changed = analysed is None or C.difference(sig, analysed) > C.CHANGED
        prev = sig
        if time.monotonic() - last_window_check > 2:
            follow_window(shot)
        if args.auto_click:
            pressed = hotkeys.key_down(hotkeys.VK_F8)
            if pressed and not auto["f8"]:  # F8 toggles
                auto["on"] = not auto["on"]
                say("auto-click resumed (F8)" if auto["on"] else "auto-click paused (F8 resumes)")
                show(view[0], view[1].split(" | AUTO")[0] + auto_note(), view[3])
            auto["f8"] = pressed
            auto["f9"] = auto["f9"] or hotkeys.key_down(hotkeys.VK_F9)  # --step: one click per F9
            if auto["awaiting"] is not None:
                if changed:
                    auto["awaiting"] = None  # the game reacted to the click
                elif time.monotonic() - auto["awaiting"] > 3.0:
                    auto["on"], auto["awaiting"], analysed = False, None, None  # re-read the board once F8 resumes
                    show([], "the click had no effect: auto-click paused (F8 resumes)", ("NO RESPONSE", ERROR))
                    say("the last click had no effect (a dialog in the way?): auto-click paused, F8 resumes")
        if stable or not changed:
            said["moving"] = None
        if changed and not stable:
            if view[3][0] != "WAITING":  # redraw only when the state changes
                show([], "the board is moving", ("WAITING", WAIT))
            analysed = None  # whatever it settles on gets analysed
            said["moving"] = said["moving"] or time.monotonic()
            if time.monotonic() - said["moving"] > MOVING_TOO_LONG:
                say(f"the screen has kept moving for {MOVING_TOO_LONG:.0f} s (an animation?): no marks until it is "
                    "still")
        elif changed:
            show([], "reading the board and searching for the best tap", ("ANALYZING...", BUSY))
            started = time.monotonic()
            a = B.analyze(shot, memory, budget=args.budget, think=args.think, threads=args.threads)
            done, asked = S.LAST_LOOKAHEAD
            if a is not None and done < asked:
                say(f"the look-ahead's time cap ({args.budget:g} s) cut in: {done} of {asked} guessed boards searched")
            took = time.monotonic() - started
            if rec is not None:
                spots = [] if a is None else [B.spot(t) for t in a.frame.tiles if t.free]
                if a is None and game["board"]:
                    game["board"], game["gone"] = False, time.monotonic()
                elif a is not None and not game["board"]:
                    if game["spots"] and not recorder.same_game(game["spots"], spots):
                        rec.new_game()  # (before this board is fed: it belongs to the new folder)
                    game["board"] = True
                if a is not None:
                    game["spots"] = spots
            if a is None:
                show([], "no game board on the device screen - open the minigame", ("NO BOARD", ERROR))
                say("no game board on the device screen (a dialog, a menu or the result screen)")
            else:
                show(B.build_marks(a, args.labels), f"{B.status_line(a)} | {took:.1f}s{auto_note()}", ("READY", READY))
                if B.at_risk(a):  # worth a booster? (only on risky boards: it takes a few seconds)
                    show(view[0], view[1] + " | checking boosters...", ("READY", READY))
                    tip = B.booster_advice(a, budget=2 * args.budget)
                    show(view[0], view[1].split(" | checking boosters")[0] + " | " + tip, ("READY", READY))
                    say(tip)
            analysed = sig
            auto["pending"] = None
            if a is not None and args.auto_click and maybe_click(a, sig):
                auto["pending"] = (a, sig)
            if time.monotonic() - last_save > 30:
                lib.save()
                last_save = time.monotonic()
        if args.auto_click and auto["pending"] is not None and not changed and stable:
            a, sig_a = auto["pending"]  # a suggestion that was not allowed yet (start-up delay, F8 pause, F9 step)
            auto["pending"] = (a, sig_a) if maybe_click(a, sig_a) else None
        if rec is not None and (game["board"] or time.monotonic() - game["gone"] < RECORD_AFTER):
            rec.feed(shot)  # (the recorder keeps the settled boards; menus long after the game are left out)

    overlay.root.after(100, tick)
    try:
        overlay.root.mainloop()
    except KeyboardInterrupt:
        pass
    if rec is not None:
        rec.close()
    source.close()
    lib.save()
    return 0


def add_adb_options(p: argparse.ArgumentParser) -> None:
    p.add_argument("--serial", default=C.DEFAULT_SERIAL, help=f"ADB address of the device (default {C.DEFAULT_SERIAL})")
    p.add_argument("--adb-exe", help="path to adb.exe (default: on PATH, else BlueStacks' HD-Adb.exe)")


def _stop_when_input_closes() -> None:
    """Ctrl+C for this process once the launcher closes our input (its Stop button). On Windows this polls the pipe
    instead of waiting in a read: while a read was pending on stdin, importing numba hung for good (the advisor sat at
    "preparing the search to the end of the game...")."""
    if sys.platform != "win32":
        sys.stdin.read()
        _thread.interrupt_main()
        return
    import _winapi
    import msvcrt

    handle = msvcrt.get_osfhandle(sys.stdin.fileno())
    while True:
        try:
            _winapi.PeekNamedPipe(handle, 0)
        except OSError:  # the launcher closed its end
            _thread.interrupt_main()
            return
        time.sleep(0.3)


def main() -> int:
    global KIND_FILE
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--profile", default=G.DEFAULT_NAME, help=f"game profile in profiles/ (available: {', '.join(G.available())})")
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="live overlay")
    r.add_argument("--labels", action="store_true", help="draw the kind letter on every tile")
    r.add_argument("--interval", type=int, default=250, help="ms between screenshots")
    r.add_argument("--max-risk", type=int, default=round(B.MAX_RISK * 100),
                   help="auto-click waits for you when the best tap's risk is above this (percent)")
    r.add_argument("--no-record", action="store_true", help="do not record the games (each game goes to recordings/<profile>/ by default)")
    r.add_argument("--budget", type=float, default=B.LOOK_CAP,
                   help="safety cap (s) for the look-ahead; it normally finishes all its guessed boards long before")
    r.add_argument("--threads", type=int, default=None,
                   help="CPU threads for the search to the end of the game (default: 16, at most all cores but one)")
    r.add_argument("--think", type=float, default=3.0,  # benchmark.py: 2-20 s make the same decisions (5-7 % blunders on
                   # the hard ones, all from hidden icons); 3 s keeps a margin
                   help="seconds on top for the search to the end of the game (0 = only the short look-ahead)")
    r.add_argument("--auto-click", action="store_true", help="tap the best tile while the script is confident")
    r.add_argument("--max-clicks", type=int, default=200, help="stop clicking after this many taps")
    r.add_argument("--click-delay", type=float, default=0.6, help="seconds to wait after a click before looking again")
    r.add_argument("--step", action="store_true", help="with --auto-click: click only after you press F9")
    add_adb_options(r)
    r.set_defaults(fn=cmd_run)
    rec = sub.add_parser("record", help="save every settled board while you play (test data for the tool)")
    rec.add_argument("--out", help=f"folder for the frames (default: {RECORDINGS.name}/<profile>/<date-time>)")
    rec.add_argument("--interval", type=int, default=250, help="ms between screenshots")
    add_adb_options(rec)
    rec.set_defaults(fn=cmd_record)
    sub.add_parser("data", help="how much useful test data the recordings hold").set_defaults(fn=cmd_data)
    ev = sub.add_parser("evaluate", help="accuracy of the tile reading against what the recorded games revealed")
    ev.add_argument("recordings", nargs="*", help="recording folders (default: all)")
    ev.set_defaults(fn=cmd_evaluate)
    adv = sub.add_parser("advice", help="how often reading errors change the advice, on the recorded games")
    adv.add_argument("recordings", nargs="*", help="recording folders (default: all)")
    adv.add_argument("--every", type=int, default=1, help="only every n-th board (faster)")
    adv.set_defaults(fn=cmd_advice)
    sub.add_parser("train", help="learn the icons from the recorded games of the profile").set_defaults(fn=cmd_train)
    an = sub.add_parser("analyze", help="analyse one screenshot")
    an.add_argument("--image", required=True)
    an.add_argument("--out", help="annotated PNG")
    an.add_argument("--labels", action="store_true")
    an.add_argument("--kinds", help="kind library file to load/save (default: fresh, not saved)")
    an.add_argument("--samples", type=int, default=None, help="guessed boards of the look-ahead (default: solver.LOOK_SAMPLES)")
    an.add_argument("--depth", type=int, default=None, help="taps it looks ahead (default: solver.LOOK_DEPTH)")
    an.set_defaults(fn=cmd_analyze)
    args = p.parse_args()
    if hasattr(signal, "SIGBREAK"):  # Ctrl+Break ends like Ctrl+C (saves first)
        signal.signal(signal.SIGBREAK, signal.default_int_handler)
    if os.environ.get("HELPER_STOP_ON_EOF"):  # started by gui.py: its Stop button closes our input
        threading.Thread(target=_stop_when_input_closes, daemon=True).start()

    profile = G.load(args.profile)
    G.activate(profile)
    KIND_FILE = profile.dir / "kinds.npz"
    old = HERE / "kinds.npz"  # before profiles, the learned library sat next to this script
    if args.profile == G.DEFAULT_NAME and old.exists() and not KIND_FILE.exists():
        shutil.move(str(old), str(KIND_FILE))
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
