"""Test helper: the inline script of an HTML page, read with a real HTML parser (not a regular expression)."""

from html.parser import HTMLParser


class _Scripts(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.scripts: list[str] = []
        self._in_script = False

    def handle_starttag(self, tag, attrs):
        if tag == "script":
            self._in_script = True
            if not any(name == "src" for name, _ in attrs):
                self.scripts.append("")

    def handle_endtag(self, tag):
        if tag == "script":
            self._in_script = False

    def handle_data(self, data):
        if self._in_script and self.scripts:
            self.scripts[-1] += data


def inline_script(html: str) -> str:
    """The text of the page's first script that has no `src`."""
    parser = _Scripts()
    parser.feed(html)
    parser.close()
    return parser.scripts[0]
