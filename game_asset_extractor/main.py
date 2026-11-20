"""Game Asset Extractor: the images of Last Asylum: Plague (BlueStacks, through ADB) for the webapp.

    python main.py check                       is the device reachable, which game and resource version
    python main.py scan                        what is new / changed in the game since the last pull
    python main.py pull                        scan, then copy the new / changed bundles into cache/
    python main.py extract                     cut the pulled bundles into PNGs (out/<type>/<group>/<name>.png)
    python main.py match                       which sprites the webapp already has (out/matches.json)
    python main.py gallery [--serve]           write out/index.html (--serve: and open it on a local server, where tags can be edited)
    python main.py baseline                    mark everything extracted so far as seen (NEW / CHANGED start over)
    python main.py history                     write history.json (which version added / changed what) from the cache; commit it
    python main.py update                      pull + extract + match + gallery
    python main.py status                      how many webapp images are official (made from the game's pictures)
    python main.py map [--accept DIST]         map webapp images to game pictures (hash suggestions; the window edits by hand)
    python main.py sync [--apply]              make the mapped webapp files from the game pictures (preview without --apply)
    python main.py import <id> <dest>          add a sprite to webapp/public/assets as a new image and map it
    python main.py texts                       write the text browser, out/texts/index.html (every extracted game text)
    python main.py text-status                 how many of the webapp's texts are the game's own (text_mapping.json)
    python main.py text-map [--accept]         take the game text every suggested webapp text has (the window's editor does the rest)
    python main.py text-sync [--apply]         write the game's wording and translations into the webapp's data files (preview without --apply)

The pictures and the game's texts, tables and scripts are always taken; `--types` (scan, pull, update) adds optional kinds of
bundles: `effects`, `models`, `scenes`, `layouts`, `other`, a comma-separated list or `all`. `start_gui.bat` opens the same in a window (`gui.py`).
"""

from __future__ import annotations

import argparse
import sys
import threading
import webbrowser

import config as C
import device as D
import extract as E
import gallery as G
import history as H
import importer as I
import mapping as Mp
import match as M
import state as S
import pull as P
import scan as Sc
import text_browser as TB
import text_mapping as TM
import texts as T


def connect(args) -> D.Device:
    return D.Device(args.serial, args.adb_exe)


def do_check(args) -> None:
    dev = connect(args)
    _, version = dev.read_manifest()
    print(f"OK  {dev.serial}: {C.PACKAGE} {dev.app_version()}, resource version {version}")


def do_scan(args) -> dict:
    result = Sc.scan(connect(args), Sc.parse_types(args.types))
    print("\n".join(Sc.summary_lines(result)))
    return result


def do_pull(args) -> None:
    dev = connect(args)
    types = Sc.parse_types(args.types)
    result = Sc.scan(dev, types)
    print("\n".join(Sc.summary_lines(result)))
    todo = {**result["new"], **result["changed"]}
    if not todo:
        print("nothing to pull")
        return
    print(f"pulled: {P.pull(dev, todo, result['version'])}")
    Sc.scan(dev, types)  # what is left (a failed bundle), for the window's table


def do_extract(args) -> None:
    print(f"extracted: {E.run(args.force)}")


def do_baseline(args) -> None:
    run = E.mark_seen()
    print(f"everything up to extract run {run} counts as seen: {G.write()}")
    if (C.OUT / "texts" / "index.html").is_file():  # the text browser's NEW / CHANGED start over too
        print(f"texts: {TB.write()}")


def do_history(args) -> None:
    history = H.record(S.load_index(), T.load_index())
    if history is None:
        raise ValueError("nothing extracted yet: no history to write")
    print(f"history: {H.PATH} - {len(history['runs'])} runs, {len(history['pictures']['changes'])} pictures and "
          f"{len(history['texts']['changes'])} texts that came after the first run or changed")


def do_match(args) -> None:
    found = M.run()
    close = sum(1 for c in found.values() if c and c[0]["dist"] <= M.CLOSE)
    print(f"{len(found)} webapp images compared, {close} have a close sprite (distance <= {M.CLOSE})")


def do_gallery(args) -> None:
    if not args.serve:
        print(f"gallery: {G.write()}")
        return
    server, url = G.start()
    print(f"gallery: {url} (Ctrl+C stops the server)", flush=True)
    webbrowser.open(url)
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        G.stop(server)


def do_update(args) -> None:
    do_pull(args)
    args.force = False
    do_extract(args)
    do_match(args)
    do_gallery(args)


def do_import(args) -> None:
    focus = tuple(float(v) for v in args.focus.split(",")) if args.focus else None
    if focus is not None and len(focus) != 2:
        raise ValueError("--focus takes x,y (0 = left / top, 1 = right / bottom), e.g. 0.5,0.1")
    target, note = I.import_picture(args.id, args.dest, args.force, focus, args.resize)
    print(f"imported {args.id} -> {target} ({note}); mapped; gallery: {G.write()}")


def do_status(args) -> None:
    table = Mp.rows(Mp.load(), S.load_index(), Mp.load_matches())
    print(Mp.summary(table))
    for status in ("to sync", "gone", "missing", "suggested", "unmapped"):
        names = [r["rel"] for r in table if r["status"] == status]
        if names:
            print(f"{status} ({len(names)}): {', '.join(names[:12])}{' ...' if len(names) > 12 else ''}")


def do_map(args) -> None:
    if args.accept is not None:
        table = Mp.rows(Mp.load(), S.load_index(), Mp.load_matches())
        print(f"mapped {Mp.accept_suggestions(table, args.accept)} images to their closest game picture (distance <= {args.accept})")
    do_status(args)


def do_sync(args) -> None:
    done = Mp.sync(S.load_index(), args.apply, args.force)
    for d in done:
        print(f"{d['action']:7s} {d['rel']}  ({d['note']})")
    writes = sum(d["action"] == "write" for d in done)
    print(f"{writes} files {'written' if args.apply else 'would be written'}, "
          f"{sum(d['action'] == 'same' for d in done)} already identical, {sum(d['action'] == 'skipped' for d in done)} skipped"
          + ("" if args.apply or not done else "  (preview: add --apply to write them)"))


def text_table() -> list[dict]:
    """The webapp's texts against the game's, one row each (`text_mapping.rows`)."""
    _, texts = TM.read_webapp()
    return TM.rows(TM.load(), texts, TM.Game(T.load()), TM.webapp_languages())


def do_texts(args) -> None:
    print(f"texts: {TB.write()}")


def do_text_status(args) -> None:
    table = text_table()
    print(TM.summary(table))
    for status in ("to sync", "mismatch", "missing", "suggested", "ambiguous", "near", "unmapped"):
        names = [r["location"] for r in table if r["status"] == status]
        if names:
            print(f"{status} ({len(names)}): {', '.join(names[:8])}{' ...' if len(names) > 8 else ''}")


def do_text_map(args) -> None:
    if args.accept:
        print(f"mapped {TM.accept_suggestions(text_table())} webapp texts to the game text their English is the same as")
    do_text_status(args)


def do_text_sync(args) -> None:
    done = TM.sync(args.apply)
    for d in done:
        where = f"{d['location']} [{d['lang']}]" if d["lang"] else d["location"]
        print(f"write   {where}: {d['old']!r} -> {d['new']!r}" if d["action"] == "write" else f"skipped {where}: {d['note']}")
    writes = sum(d["action"] == "write" for d in done)
    print(f"{writes} texts {'written' if args.apply else 'would be written'}, {sum(d['action'] == 'skipped' for d in done)} skipped"
          + ("" if args.apply or not writes else "  (preview: add --apply to write them)"))


# the commands that read or write the webapp's pictures or data files
NEEDS_WEBAPP = ("match", "update", "map", "status", "sync", "import", "text-status", "text-map", "text-sync")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--serial", default=C.DEFAULT_SERIAL, help="ADB address (BlueStacks: Settings > Advanced)")
    p.add_argument("--adb-exe", default=None, help="path of adb / HD-Adb.exe (found by itself in the usual places)")
    sub = p.add_subparsers(dest="command", required=True)

    def command(name, fn, help_, bundles=False):
        c = sub.add_parser(name, help=help_)
        c.set_defaults(fn=fn, force=False, serve=False, types=",".join(C.REQUIRED_TYPES))
        if bundles:
            c.add_argument("--types", default=",".join(C.REQUIRED_TYPES),
                           help=f"bundle types to take besides {' and '.join(C.REQUIRED_TYPES)} (always taken): all or a list of "
                                f"{', '.join(t for t in C.TYPES if t not in C.REQUIRED_TYPES)}")
        return c

    command("check", do_check, "is the device reachable?")
    command("scan", do_scan, "what is new / changed since the last pull", bundles=True)
    command("pull", do_pull, "scan, then copy the new / changed bundles into cache/", bundles=True)
    command("extract", do_extract, "cut the pulled bundles into PNGs").add_argument(
        "--force", action="store_true", help="extract bundles again even if nothing changed")
    command("match", do_match, "which sprites the webapp already has")
    command("gallery", do_gallery, "write out/index.html").add_argument(
        "--serve", action="store_true", help="serve it on this computer only and open it, so tags can be edited in it")
    command("baseline", do_baseline, "mark everything extracted so far as seen (the gallery's NEW / CHANGED start over)")
    command("history", do_history, "write history.json (which version added / changed what) from the cache")
    command("update", do_update, "pull + extract + match + gallery", bundles=True)
    command("status", do_status, "how many webapp images are official (made from the game's own pictures)")
    command("map", do_map, "map webapp images to game pictures (the window's editor does it by hand)").add_argument(
        "--accept", type=int, metavar="DIST", help="map every unmapped image to its closest picture within this distance (0-256; 10 = near-identical)")
    sy = command("sync", do_sync, "make the webapp's files from the game pictures they are mapped to (preview unless --apply)")
    sy.add_argument("--apply", action="store_true", help="write the files (without it nothing changes)")
    sy.add_argument("--force", action="store_true", help="rebuild files that are already up to date too")
    imp = command("import", do_import, "add a sprite to webapp/public/assets as a new image and map it")
    imp.add_argument("id", help="sprite id: <type>/<group>/<name>, as the gallery shows it")
    imp.add_argument("dest", help="<folder>/<name> in the assets folder, e.g. items/chest/gold (events/ become .webp)")
    imp.add_argument("--force", action="store_true", help="replace an existing file")
    imp.add_argument("--resize", action="store_true",
                     help="make an event banner 720x360 even if it is close to 2:1 (else it keeps the game's size)")
    imp.add_argument("--focus", help="x,y of the crop window for a picture of another aspect: 0 = left / top, 1 = right / bottom")
    command("texts", do_texts, "write the text browser, out/texts/index.html")
    command("text-status", do_text_status, "how many of the webapp's texts are the game's own")
    command("text-map", do_text_map, "take the game text every suggested webapp text has").add_argument(
        "--accept", action="store_true", help="map every suggested text (its English is in the game with one translation); near and ambiguous ones are never taken")
    command("text-sync", do_text_sync, "write the game's wording and translations into the webapp's data files (preview unless --apply)").add_argument(
        "--apply", action="store_true", help="write the files (without it nothing changes)")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command in NEEDS_WEBAPP:
            C.require_webapp()
        args.fn(args)
    except (RuntimeError, OSError, ValueError) as e:
        print(f"!! {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
