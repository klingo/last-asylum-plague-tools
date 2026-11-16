"""Test helper: the scripts and the text of an HTML page, read with a real HTML parser (not a regular expression)."""

from html.parser import HTMLParser


class _Page(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.scripts: list[str] = []  # the inline scripts (those without a `src`)
        self.text: list[str] = []  # the text of the body outside its scripts and styles
        self._open: str | None = None
        self._in_body = False

    def handle_starttag(self, tag, attrs):
        if tag == "body":
            self._in_body = True
        elif tag in ("script", "style"):
            self._open = tag
            if tag == "script" and not any(name == "src" for name, _ in attrs):
                self.scripts.append("")

    def handle_endtag(self, tag):
        if tag == self._open:
            self._open = None

    def handle_data(self, data):
        if self._open == "script" and self.scripts:
            self.scripts[-1] += data
        elif self._open is None and self._in_body and data.strip():
            self.text.append(data.strip())


def parse(html: str) -> _Page:
    page = _Page()
    page.feed(html)
    page.close()
    return page


def inline_scripts(html: str) -> list[str]:
    return parse(html).scripts


def body_text(html: str) -> list[str]:
    return parse(html).text
