"""Plain text out of a short HTML snippet (an artist bio, a description).

Rendering that HTML would mean sanitizing it against XSS for no real
benefit (a paragraph or two, not a document): plain text is the simpler,
safer choice. Block-level tags become line breaks so paragraphs stay
readable.
"""

from __future__ import annotations

import html
import re
from html.parser import HTMLParser
from typing import Any


class _TextExtractor(HTMLParser):
    _BLOCK_TAGS = frozenset({
        'p',
        'br',
        'div',
        'li',
        'ul',
        'ol',
        'h1',
        'h2',
        'h3',
        'h4',
    })

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: Any) -> None:
        if tag in self._BLOCK_TAGS:
            self._parts.append('\n')

    def handle_endtag(self, tag: str) -> None:
        if tag in self._BLOCK_TAGS:
            self._parts.append('\n')

    def handle_data(self, data: str) -> None:
        self._parts.append(data)

    def text(self) -> str:
        joined = html.unescape(''.join(self._parts))
        # Collapse the blank-line runs the tag-per-line pass above
        # tends to produce, and trim trailing spaces on each line.
        lines = [ln.strip() for ln in joined.splitlines()]
        out: list[str] = []
        for ln in lines:
            if ln or (out and out[-1]):
                out.append(ln)
        return '\n'.join(out).strip()


def strip_html(text: str) -> str:
    """Plain-text rendering of a (possibly-HTML) snippet."""

    if not text:
        return ''
    if '<' not in text:
        return html.unescape(text).strip()
    parser = _TextExtractor()
    try:
        parser.feed(text)
    except Exception:
        # Malformed markup: better a few stray tags than no text.
        return re.sub(r'<[^>]+>', ' ', text).strip()
    return parser.text()
