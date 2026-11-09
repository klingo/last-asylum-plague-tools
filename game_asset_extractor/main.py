"""Game Asset Extractor: the images of Last Asylum: Plague (BlueStacks, through ADB) for the webapp.

    python main.py check                       is the device reachable, which game and resource version
    python main.py scan                        what is new / changed in the game since the last pull
    python main.py pull                        scan, then copy the new / changed bundles into cache/
    python main.py extract                     cut the pulled bundles into PNGs (out/<group>/<name>.png)
    python main.py match                       which sprites the webapp already has (out/matches.json)
    python main.py gallery                     write out/index.html
    python main.py baseline                    mark everything extracted so far as seen (NEW / CHANGED start over)
    python main.py update                      pull + extract + match + gallery
    python main.py status                      how many webapp images are official (made from the game's pictures)
    python main.py map [--accept DIST]         map webapp images to game pictures (hash suggestions; the window edits by hand)
    python main.py sync [--apply]              make the mapped webapp files from the game pictures (preview without --apply)
    python main.py import <id> <dest>          add a sprite to webapp/public/assets as a new image and map it

`--types` (scan, pull, update) picks the kinds of bundles to look at: `pictures` (default), `effects`, `models`,
`scenes`, `layouts`, `data`, `other`, a comma-separated list or `all`; `--filter REGEX` narrows the bundles by their
Unity path. `start_gui.bat` opens the same in a window (`gui.py`).
"""

from __future__ import annotations

import argparse
import sys

import config as C
import device as D
import extract as E
import gallery as G
import importer as I
import mapping as Mp
import match as M
import state as S
import pull as P
import scan as Sc


def connect(args) -> D.Device:
    return D.Device(args.serial, args.adb_exe)


def do_check(args) -> None:
    dev = connect(args)
    _, version = dev.read_manifest()
    print(f"OK  {dev.serial}: {C.PACKAGE} {dev.app_version()}, resource version {version}")


def do_scan(args) -> dict:
    result = Sc.scan(connect(args), Sc.parse_types(args.types), args.filter)
    print("\n".join(Sc.summary_lines(result)))
    return result


def do_pull(args) -> None:
    dev = connect(args)
    types = Sc.parse_types(args.types)
    result = Sc.scan(dev, types, args.filter)
    print("\n".join(Sc.summary_lines(result)))
    todo = {**result["new"], **result["changed"]}
    if not todo:
        print("nothing to pull")
        return
    print(f"pulled: {P.pull(dev, todo, result['version'])}")
    Sc.scan(dev, types, args.filter)  # what is left (a failed bundle), for the window's table


def do_extract(args) -> None:
    print(f"extracted: {E.run(args.filter, args.force)}")


def do_baseline(args) -> None:
    run = E.mark_seen()
    print(f"everything up to extract run {run} counts as seen: {G.write()}")


def do_match(args) -> None:
    found = M.run()
    close = sum(1 for c in found.values() if c and c[0]["dist"] <= M.CLOSE)
    print(f"{len(found)} webapp images compared, {close} have a close sprite (distance <= {M.CLOSE})")


def do_gallery(args) -> None:
    print(f"gallery: {G.write()}")


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
    for status in ("to sync", "missing", "suggested", "unmapped"):
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


NEEDS_WEBAPP = ("match", "update", "map", "status", "sync", "import")  # the commands that read or write the webapp's pictures


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--serial", default=C.DEFAULT_SERIAL, help="ADB address (BlueStacks: Settings > Advanced)")
    p.add_argument("--adb-exe", default=None, help="path of adb / HD-Adb.exe (found by itself in the usual places)")
    sub = p.add_subparsers(dest="command", required=True)

    def command(name, fn, help_, bundles=False):
        c = sub.add_parser(name, help=help_)
        c.set_defaults(fn=fn, force=False, types=",".join(C.DEFAULT_TYPES), filter=None)
        if bundles:
            c.add_argument("--filter", help="only bundles whose Unity path matches this regex (case-insensitive)")
        if bundles and name != "extract":
            c.add_argument("--types", default=",".join(C.DEFAULT_TYPES),
                           help=f"bundle types: all or a list of {', '.join(C.TYPES)} (default: pictures)")
        return c

    command("check", do_check, "is the device reachable?")
    command("scan", do_scan, "what is new / changed since the last pull", bundles=True)
    command("pull", do_pull, "scan, then copy the new / changed bundles into cache/", bundles=True)
    command("extract", do_extract, "cut the pulled bundles into PNGs", bundles=True).add_argument(
        "--force", action="store_true", help="extract bundles again even if nothing changed")
    command("match", do_match, "which sprites the webapp already has")
    command("gallery", do_gallery, "write out/index.html")
    command("baseline", do_baseline, "mark everything extracted so far as seen (the gallery's NEW / CHANGED start over)")
    command("update", do_update, "pull + extract + match + gallery", bundles=True)
    command("status", do_status, "how many webapp images are official (made from the game's own pictures)")
    command("map", do_map, "map webapp images to game pictures (the window's editor does it by hand)").add_argument(
        "--accept", type=int, metavar="DIST", help="map every unmapped image to its closest picture within this distance (0-256; 10 = near-identical)")
    sy = command("sync", do_sync, "make the webapp's files from the game pictures they are mapped to (preview unless --apply)")
    sy.add_argument("--apply", action="store_true", help="write the files (without it nothing changes)")
    sy.add_argument("--force", action="store_true", help="rebuild files that are already up to date too")
    imp = command("import", do_import, "add a sprite to webapp/public/assets as a new image and map it")
    imp.add_argument("id", help="sprite id: <group>/<name>, as the gallery shows it")
    imp.add_argument("dest", help="<folder>/<name> in the assets folder, e.g. items/chest/gold (events/ become .webp)")
    imp.add_argument("--force", action="store_true", help="replace an existing file")
    imp.add_argument("--resize", action="store_true",
                     help="make an event banner 720x360 even if it is close to 2:1 (else it keeps the game's size)")
    imp.add_argument("--focus", help="x,y of the crop window for a picture of another aspect: 0 = left / top, 1 = right / bottom")
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
