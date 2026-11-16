"""The local server behind the viewer: `viewer/index.html` plus two JSON routes, on this computer only (127.0.0.1).

`/api/weeks` lists the weeks that have a file (newest first), `/api/week/<year>-W<week>` is that week's table
(`aggregate.week_table`). The page itself only filters and sorts. Shared by `main.py view` and the window's button.
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

WEEK_ID = re.compile(r"^\d{4}-W\d{2}$")  # the only thing a request may name: no path can be built from it


def make_handler(directory: Path, viewer_dir: Path) -> type[http.server.BaseHTTPRequestHandler]:
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
            if path in ("/", "/index.html"):
                page = (viewer_dir / "index.html").read_bytes()
                self.reply(200, page, "text/html; charset=utf-8")
            elif path == "/api/weeks":
                self.json(list(reversed(store.list_weeks(directory))))
            elif path.startswith("/api/week/") and WEEK_ID.match(path[len("/api/week/") :]):
                week = store.load(path[len("/api/week/") :], directory)
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
