"""Pull: copy the bundles a scan found (new + changed) from the device into cache/, checked against the manifest's md5.

A bundle already in cache/ with the right md5 is not pulled again, so a stopped run continues where it ended.
`state/pulled.json` is written every few bundles and at the end.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import config as C
import state as S

SAVE_EVERY = 25  # bundles


def file_md5(path: Path) -> str:
    h = hashlib.md5()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def pull(device, items: dict[str, dict], version: str) -> dict:
    """Pull `items` ({file name: entry of scan.entries_of}); returns the counts."""
    pulled = S.load("pulled.json")
    counts = {"pulled": 0, "cached": 0, "failed": 0}
    total = len(items)
    try:
        for i, (name, e) in enumerate(sorted(items.items()), 1):
            dest = C.CACHE / name
            if dest.exists() and file_md5(dest) == e["md5"]:
                counts["cached"] += 1
            else:
                try:
                    device.fetch(name, dest)
                    if file_md5(dest) != e["md5"]:
                        raise RuntimeError("md5 differs from the manifest")
                    counts["pulled"] += 1
                except (RuntimeError, OSError) as err:  # incl. a bundle the game has not downloaded yet
                    dest.unlink(missing_ok=True)
                    counts["failed"] += 1
                    print(f"!! {name}: {err}", flush=True)
                    continue
            pulled[name] = {"md5": e["md5"], "path": e["path"]}
            if i % SAVE_EVERY == 0:
                S.save("pulled.json", pulled)
                print(f"progress pull: {i * 100 // total} %", flush=True)
    finally:
        S.save("pulled.json", pulled)
        (C.STATE / "version.txt").write_text(version, encoding="utf-8")
    return counts
