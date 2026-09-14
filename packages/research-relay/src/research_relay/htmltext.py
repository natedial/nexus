from __future__ import annotations

from html.parser import HTMLParser


_SKIP_TAGS = frozenset({"script", "style", "head", "noscript"})
_VOID_REMOTE = frozenset({"img", "iframe", "embed", "object", "source", "video", "audio", "link"})
_BLOCK_TAGS = frozenset({"p", "div", "br", "tr", "li", "h1", "h2", "h3", "h4", "h5", "h6", "blockquote", "pre"})


class _HTMLToText(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._chunks: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag in _SKIP_TAGS:
            self._skip += 1
            return
        if tag in _VOID_REMOTE:
            return
        if tag in _BLOCK_TAGS:
            self._chunks.append("\n")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in _SKIP_TAGS and self._skip:
            self._skip -= 1
            return
        if tag in {"p", "div", "tr", "li"}:
            self._chunks.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip:
            return
        self._chunks.append(data)

    def text(self) -> str:
        raw = "".join(self._chunks)
        lines = [line.strip() for line in raw.splitlines()]
        compacted: list[str] = []
        blank = False
        for line in lines:
            if not line:
                if not blank and compacted:
                    compacted.append("")
                blank = True
                continue
            compacted.append(line)
            blank = False
        return "\n".join(compacted).strip()


def html_to_text(html: str) -> str:
    parser = _HTMLToText()
    try:
        parser.feed(html or "")
        parser.close()
    except Exception:
        return (html or "").strip()
    return parser.text()
