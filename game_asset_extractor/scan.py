"""Scan: which bundles of the game are new or changed compared with what was already pulled?

The game's manifest (`ABAsset/Version.txt`, 5'000+ entries) lists every bundle with its original Unity path
(`pathName`), file name, md5 and size in KB, so a scan reads one small file and downloads nothing. It compares the
manifest with `state/pulled.json` (file name -> {md5, path} of what was pulled):

    new         in the manifest, never pulled
    changed     pulled, but the md5 differs now
    unchanged   pulled and still the same
    removed     pulled, no longer in the manifest (at all, whatever types are scanned)

Only the chosen types count (`config.TYPES`: pictures, game texts, effects, models, ... by the start of the `pathName`; the
pictures and the game texts, `config.REQUIRED_TYPES`, are always in). A bundle's `group` is the folder it sits in, which is how the window sorts them:
`UI/Atlas/Module/Zombie_ItemIcon144/Zombie_ItemIcon144Atlas.prefab` -> `Zombie_ItemIcon144`,
`UITexture/DynamicTexture/BigBg/x.png` -> `BigBg`.
"""

from __future__ import annotations

import config as C
import state as S


def group_of(path_name: str) -> str:
    """The folder a bundle's asset sits in (the last folder, or the name itself for a folder bundle)."""
    parts = path_name.split("/")
    return parts[-2] if "." in parts[-1] and len(parts) > 1 else parts[-1]


def type_of(path_name: str) -> str:
    """The key of `config.TYPES` a bundle belongs to."""
    for key, (_, prefixes) in C.TYPES.items():
        if prefixes and path_name.startswith(prefixes):
            return key
    return "other"


def parse_types(text: str) -> tuple[str, ...]:
    """`--types` value: comma-separated keys of `config.TYPES`, or `all`. The required types are always in, in `config.TYPES`' order."""
    if text.strip() == "all":
        return tuple(C.TYPES)
    keys = {k.strip() for k in text.split(",") if k.strip()}
    unknown = sorted(keys - set(C.TYPES))
    if unknown:
        raise ValueError(f"unknown type {', '.join(unknown)}: use all or a list of {', '.join(C.TYPES)}")
    return tuple(k for k in C.TYPES if k in keys or k in C.REQUIRED_TYPES)


def entries_of(manifest: dict) -> dict[str, dict]:
    """{file name: {path, group, type, md5, kb}} of the manifest's bundles."""
    return {
        e["fileName"]: {"path": e["pathName"], "group": group_of(e["pathName"]), "type": type_of(e["pathName"]),
                        "md5": e["md5"], "kb": e["size"]}
        for e in manifest.get("abList", [])
    }


def select(entries: dict[str, dict], types=C.REQUIRED_TYPES) -> dict[str, dict]:
    """The entries of the chosen types."""
    return {n: e for n, e in entries.items() if e["type"] in types}


def diff(wanted: dict[str, dict], pulled: dict[str, dict], known=None) -> dict:
    """Classify the wanted entries against `pulled` ({file name: {md5, path}}). `known` = every file name of the
    manifest: a pulled bundle is only "removed" when the game dropped it, not when its type is just not scanned."""
    known = wanted if known is None else known
    new = {n: e for n, e in wanted.items() if n not in pulled}
    changed = {n: e for n, e in wanted.items() if n in pulled and pulled[n]["md5"] != e["md5"]}
    unchanged = {n: e for n, e in wanted.items() if n in pulled and n not in changed}
    return {"new": new, "changed": changed, "unchanged": unchanged, "removed": sorted(n for n in pulled if n not in known)}


def by_type(result: dict) -> list[dict]:
    """Rows for the window: per scanned type its new / changed / unchanged counts and the MB to download, with its
    groups (folders) below, those with news first. The type's order is `config.TYPES`'."""
    types: dict[str, dict] = {}
    for kind in ("new", "changed", "unchanged"):
        for e in result[kind].values():
            t = types.setdefault(e["type"], {"type": e["type"], "label": C.TYPES[e["type"]][0], "new": 0, "changed": 0,
                                             "unchanged": 0, "kb": 0, "groups": {}})
            g = t["groups"].setdefault(e["group"], {"group": e["group"], "new": 0, "changed": 0, "unchanged": 0, "kb": 0})
            for row in (t, g):
                row[kind] += 1
                row["kb"] += e["kb"] if kind != "unchanged" else 0
    rows = [types[k] for k in C.TYPES if k in types]
    for t in rows:
        t["groups"] = sorted(t["groups"].values(), key=lambda g: (-(g["new"] + g["changed"]), g["group"].lower()))
    return rows


def scan(device, types=C.REQUIRED_TYPES) -> dict:
    """Read the device's manifest, compare it with what was pulled, save and return the result."""
    manifest, version = device.read_manifest()
    entries = entries_of(manifest)
    result = diff(select(entries, types), S.load("pulled.json"), known=entries)
    result.update(version=version, types=list(types))
    S.save("scan.json", result)
    return result


def summary_lines(result: dict) -> list[str]:
    n, c, u, r = (len(result[k]) for k in ("new", "changed", "unchanged", "removed"))
    kb = sum(e["kb"] for kind in ("new", "changed") for e in result[kind].values())
    lines = [f"resource version {result['version']}: {n} new, {c} changed, {u} unchanged, {r} removed "
             f"({kb / 1024:.0f} MB to download)"]
    for t in by_type(result):
        lines.append(f"{t['label']}: {t['new']} new, {t['changed']} changed, {t['unchanged']} unchanged")
        lines += [f"    {g['group']}: {g['new']} new, {g['changed']} changed" for g in t["groups"][:10] if g["new"] + g["changed"]]
    return lines
