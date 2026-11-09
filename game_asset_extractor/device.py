"""The Android device through ADB: its bundle manifest and the bundle files.

The game keeps its asset bundles in two places: the install-time asset pack (`split_abPack1.apk`, `assets/ABAsset/`)
and the hot-updated ones on the sdcard (`Android/data/<package>/files/ABAsset/<NN>/`). The sdcard copy wins, as in the
game. `ABAsset/Version.txt` is the game's manifest of every bundle (see `scan.py`), `VersionTime.txt` its version.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import config as C

_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0  # no console window flashing up for every adb call
APK_PREFIX = "assets/ABAsset/"
ABASSET_DIR = f"/sdcard/Android/data/{C.PACKAGE}/files/ABAsset"


def find_adb(explicit: str | None = None) -> str | None:
    for candidate in (explicit, shutil.which("adb"), *C.ADB_CANDIDATES):
        if candidate and Path(candidate).exists():
            return str(candidate)
    return None


def parse_stat(text: str) -> dict[str, str]:
    """`stat -c '%s %n'` lines of the sdcard bundles -> {file name: device path}. The last folder wins on a duplicate."""
    found = {}
    for line in text.splitlines():
        _, _, path = line.strip().partition(" ")
        if path.endswith(".assetbundles"):
            found[path.rsplit("/", 1)[-1]] = path
    return found


def parse_manifest_text(raw: bytes) -> dict:
    return json.loads(raw.decode("utf-8-sig"))


class Device:
    def __init__(self, serial: str = C.DEFAULT_SERIAL, adb: str | None = None):
        self.adb = find_adb(adb)
        if self.adb is None:
            raise RuntimeError("adb not found: install Android platform-tools or give the path (BlueStacks: HD-Adb.exe)")
        self.serial = serial
        if ":" in serial:  # network device (emulators): connect first
            out = self.run("connect", serial, device=False).decode(errors="replace")
            if "connected" not in out:
                raise RuntimeError(f"adb could not connect to {serial}: {out.strip()} (is ADB enabled in BlueStacks?)")
        self._sdcard: dict[str, str] | None = None
        self._apk: Path | None = None

    def run(self, *args: str, device: bool = True, timeout: float = 120) -> bytes:
        cmd = [self.adb, *(["-s", self.serial] if device else []), *args]
        res = subprocess.run(cmd, capture_output=True, timeout=timeout, creationflags=_NO_WINDOW)
        if res.returncode != 0:
            raise RuntimeError(f"adb {' '.join(args)} failed: {res.stderr.decode(errors='replace').strip()}")
        return res.stdout

    def shell(self, command: str, timeout: float = 120) -> str:
        return self.run("shell", command, timeout=timeout).decode(errors="replace")

    def pull(self, remote: str, local: Path, timeout: float = 600) -> None:
        local.parent.mkdir(parents=True, exist_ok=True)
        self.run("pull", remote, str(local), timeout=timeout)

    def app_version(self) -> str:
        out = self.shell(f"dumpsys package {C.PACKAGE} | grep versionName")
        return out.strip().partition("=")[2] or "not installed"

    def read_manifest(self) -> tuple[dict, str]:
        """(the game's manifest, its resource version)."""
        manifest = parse_manifest_text(self.run("exec-out", "cat", f"{ABASSET_DIR}/Version.txt"))
        version = self.run("exec-out", "cat", f"{ABASSET_DIR}/VersionTime.txt").decode("utf-8-sig").strip()
        return manifest, version

    def sdcard_bundles(self) -> dict[str, str]:
        if self._sdcard is None:
            out = self.shell(f"find {ABASSET_DIR} -type f -name '*.assetbundles' -exec stat -c '%s %n' {{}} +", timeout=300)
            self._sdcard = parse_stat(out)
        return self._sdcard

    def apk_path(self) -> Path:
        """The asset pack pulled into the cache (again only when its size changed)."""
        if self._apk is None:
            paths = [p.removeprefix("package:") for p in self.shell(f"pm path {C.PACKAGE}").split() if "abPack" in p]
            if not paths:
                raise RuntimeError("the asset pack (split_abPack1.apk) was not found on the device")
            remote = paths[0]
            size = int(self.shell(f"stat -c %s {remote}").strip())
            local = C.CACHE / "_apk" / "split_abPack1.apk"
            if not local.exists() or local.stat().st_size != size:
                print(f"pulling the asset pack ({size // 2**20} MB)...", flush=True)
                self.pull(remote, local)
            self._apk = local
        return self._apk

    def fetch(self, file_name: str, dest: Path) -> str:
        """Copy one bundle to `dest`; returns where it came from ("sdcard" / "apk")."""
        remote = self.sdcard_bundles().get(file_name)
        if remote:
            self.pull(remote, dest)
            return "sdcard"
        dest.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(self.apk_path()) as z:
            if APK_PREFIX + file_name not in z.namelist():
                raise FileNotFoundError("not on the device: the game has not downloaded it yet (play that part of the game once)")
            with z.open(APK_PREFIX + file_name) as src, open(dest, "wb") as out:
                shutil.copyfileobj(src, out)
        return "apk"
