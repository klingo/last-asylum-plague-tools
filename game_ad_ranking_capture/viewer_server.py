"""The local server behind the viewer: `viewer/index.html` plus two JSON routes, on this computer only (127.0.0.1).

`/api/weeks.json` lists the weeks that have a file (newest first), `/api/week/<year>-W<week>.json` is that week's table
(`aggregate.week_table`). The page itself only filters and sorts. The routes are the files `export.py` writes for the
static site, so the same page works here and on GitHub Pages. Shared by `main.py view` and the window's button.
"""

from __future__ import annotations

import http.server
import json
import re
import threading
from pathlib import Path

import aggregate
import config as C
import store

# the only things a request may name: no path is ever built from the request
WEEK_FILE = re.compile(r"^/api/week/(\d{4}-W\d{2})\.json$")
LANGUAGE_FILE = re.compile(r"^/i18n/([a-z]{2})\.json$")
ASSET_FILE = re.compile(r"^/assets/([a-z]+)\.png$")
PAGE_FILES = {"/": "index.html", "/index.html": "index.html", "/i18n.js": "i18n.js"}  # the page and its helper


def make_handler(directory: Path, viewer_dir: Path) -> type[http.server.BaseHTTPRequestHandler]:
    def languages() -> dict[str, Path]:
        return {path.stem: path for path in (viewer_dir / "i18n").glob("*.json")}

    def icons() -> dict[str, Path]:
        return {path.stem: path for path in (viewer_dir / "assets").glob("*.png")}

    class Handler(http.server.BaseHTTPRequestHandler):
        def reply(self, status: int, body: bytes, kind: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def json(self, value) -> None:
            self.reply(200, json.dumps(value, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

        def do_GET(self) -> None:  # noqa: N802
            path = self.path.split("?", 1)[0]
            if path in PAGE_FILES:
                kind = "text/javascript" if path.endswith(".js") else "text/html"
                self.reply(200, (viewer_dir / PAGE_FILES[path]).read_bytes(), kind + "; charset=utf-8")
            elif LANGUAGE_FILE.match(path) and LANGUAGE_FILE.match(path).group(1) in languages():
                # the file is one that exists (found by listing the folder), not a path made from the request
                language = languages()[LANGUAGE_FILE.match(path).group(1)]
                self.reply(200, language.read_bytes(), "application/json; charset=utf-8")
            elif ASSET_FILE.match(path) and ASSET_FILE.match(path).group(1) in icons():
                self.reply(200, icons()[ASSET_FILE.match(path).group(1)].read_bytes(), "image/png")
            elif path == "/api/weeks.json":
                self.json(list(reversed(store.list_weeks(directory))))
            elif WEEK_FILE.match(path):
                week = store.load(WEEK_FILE.match(path).group(1), directory)
                if week is None:
                    self.reply(404, b"no such week", "text/plain")
                else:
                    self.json(aggregate.week_table(week))
            else:
                self.reply(404, b"not found", "text/plain")

        def log_message(self, *args) -> None:  # the window has no console
            pass

    return Handler


def start(directory: Path = C.DATA_DIR, viewer_dir: Path = C.VIEWER_DIR) -> tuple[http.server.ThreadingHTTPServer, str]:
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), make_handler(directory, viewer_dir))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_address[1]}/"


def stop(server: http.server.ThreadingHTTPServer) -> None:
    server.shutdown()
    server.server_close()
