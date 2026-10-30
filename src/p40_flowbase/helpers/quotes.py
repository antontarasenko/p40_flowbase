"""
MIT License

Copyright (c) 2025 Anton Tarasenko
"""

from __future__ import annotations

import hashlib
import html.parser
import os
import pathlib
import re
import unicodedata
from decimal import Decimal
from typing import (
    NamedTuple,
    override,
)

_DASHES = dict.fromkeys(range(0x2010, 0x2016), "-") | {0x2212: "-"}
_SINGLE_QUOTES = dict.fromkeys((0x2018, 0x2019, 0x201A), "'")
_DOUBLE_QUOTES = dict.fromkeys((0x201C, 0x201D, 0x201E), '"')
_FOLDED = _DASHES | _SINGLE_QUOTES | _DOUBLE_QUOTES
_DROPPED = frozenset({0x2022, 0x00AD, 0x200B, 0x200C, 0x200D, 0xFEFF})

_NUMBER = re.compile(r"\d(?:[\d.,\u00a0 ]*\d)?")
_GROUP_SEPARATOR = re.compile(r"[.,\u00a0 ](?=\d{3}(?!\d))")
_DECIMAL = re.compile(r"^\d+(?:[.,]\d+)?$")
_MD_IMAGE = re.compile(r"!\[([^\]]*)\]\([^)]*\)")
_MD_LINK = re.compile(r"\[([^\]]*)\]\([^)]*\)")
_MD_TAG = re.compile(r"<[^>]+>")
_MD_ESCAPE = re.compile(r"\\([!-/:-@\[-`{-~])")
_MD_BLOCK_MARK = re.compile(
    r"^ {0,3}(?:#{1,6}[ \t]+|> ?|[-*+][ \t]+|\d+\.[ \t]+|\|)", re.MULTILINE
)
_MD_INLINE_MARK = re.compile(r"\*\*|__|~~|`+|\*|_|\|")


def sha256_of_text(text: str) -> str:
    """The digest of a text artifact: its UTF-8 bytes, the one encoding the
    contract declares, so producer and check hash the same thing."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class ArtifactStore:
    """Content-addressed text artifacts under one directory.

    The digest is the artifact's identity on a ``ReferenceBase`` row,
    ``artifact_sha256``: a quote is sliced from exactly these bytes, and a
    moved or re-fetched file is missing rather than silently different.
    Bytes go in and out untouched, so offsets stay valid.
    """

    def __init__(self, root: pathlib.Path | str) -> None:
        self.root = pathlib.Path(root)

    def path_of(self, sha256: str) -> pathlib.Path:
        return self.root / f"{sha256}.txt"

    def put(self, text: str) -> str:
        """Store the text once under its digest; returns the digest."""
        digest = sha256_of_text(text)
        path = self.path_of(digest)
        if not path.exists():
            self.root.mkdir(parents=True, exist_ok=True)
            temporary = path.with_name(f"{path.name}.tmp.{os.getpid()}")
            temporary.write_bytes(text.encode("utf-8"))
            temporary.replace(path)
        return digest

    def get(self, sha256: str) -> str | None:
        """The stored text, or ``None`` when absent or when its bytes no longer
        hash to the name: the store answers with exactly the bytes or nothing."""
        path = self.path_of(sha256)
        if not path.is_file():
            return None
        data = path.read_bytes()
        if hashlib.sha256(data).hexdigest() != sha256:
            return None
        return data.decode("utf-8")


def norm_map(text: str) -> tuple[str, list[int]]:
    """Fold a text to the form two renderings share, keeping the way back.

    NFKC per character, dashes and quotes to ASCII, invisible characters
    dropped, casefold, every whitespace run one space, ends stripped.
    ``offsets[i]`` is the index in ``text`` of the character that produced
    normalized character ``i``, so a match found in the folded text is cut
    from the original. One character may fold to several (a ligature), all
    mapping to the same index; combining sequences are not composed, since
    folding runs per character to keep the map exact.
    """
    out: list[str] = []
    offsets: list[int] = []
    space_from: int | None = None
    for index, char in enumerate(text):
        for folded in _fold_char(char):
            if folded.isspace():
                if space_from is None:
                    space_from = index
                continue
            if space_from is not None and out:
                out.append(" ")
                offsets.append(space_from)
            space_from = None
            out.append(folded)
            offsets.append(index)
    return "".join(out), offsets


def _fold_char(char: str) -> str:
    """One source character folded: NFKC, dashes and quotes to ASCII, invisible
    characters to nothing, casefold; whitespace is left for the caller."""
    pieces: list[str] = []
    for piece in unicodedata.normalize("NFKC", char):
        code = ord(piece)
        if code in _DROPPED:
            continue
        folded = _FOLDED.get(code, piece)
        pieces.append(folded if folded.isspace() else folded.casefold())
    return "".join(pieces)


def fold(text: str) -> str:
    """The folded text alone, for comparisons that need no way back."""
    return norm_map(text)[0]


class Resliced(NamedTuple):
    """A quote re-cut from its artifact: the exact slice, where it sits, and
    how many times its folded form occurs in the folded artifact."""

    quote: str
    start: int
    end: int
    occurrences: int


def reslice_quote(*, quote: str, artifact: str) -> Resliced | None:
    """The byte-exact slice of ``artifact`` that a quote from another rendering
    stands for, or ``None`` when the folded quote is not in the folded artifact.

    A producer stores ``Resliced.quote`` as ``quote`` and ``Resliced.start``
    as ``quote_offset_char``, and the check passes on the first try.
    """
    folded_quote = fold(quote)
    if not folded_quote:
        return None
    folded_artifact, offsets = norm_map(artifact)
    position = folded_artifact.find(folded_quote)
    if position < 0:
        return None
    start = offsets[position]
    end = offsets[position + len(folded_quote) - 1] + 1
    return Resliced(
        quote=artifact[start:end],
        start=start,
        end=end,
        occurrences=folded_artifact.count(folded_quote),
    )


def numbers_in(text: str) -> set[Decimal]:
    """Every number the text states, group separators removed.

    A comma, period, space, or no-break space followed by exactly three digits
    is read as grouping, so 1,234 and 1 234 and 1.234 are one number and the
    columns of a table stay apart; a remaining period or comma is a decimal
    mark, a remaining space a boundary. A heuristic for a row validator, with
    a known limit: a decimal with exactly three fraction digits, 0.125, reads
    as 125.
    """
    numbers: set[Decimal] = set()
    for match in _NUMBER.finditer(text):
        ungrouped = _GROUP_SEPARATOR.sub("", match.group(0))
        for token in ungrouped.replace("\u00a0", " ").split(" "):
            if _DECIMAL.match(token):
                numbers.add(Decimal(token.replace(",", ".")))
    return numbers


def value_in_quote(*, value_text: str, quote: str) -> bool:
    """True when every number the value states is stated by the quote, or the
    value states none: the gate against a true quote attached to a value it
    does not support."""
    return numbers_in(value_text) <= numbers_in(quote)


def markdown_plain(text: str) -> str:
    """A quote taken from markdown with the markdown taken out: images and
    links keep their text, tags, escapes, block and inline marks go."""
    text = _MD_IMAGE.sub(r"\1", text)
    text = _MD_LINK.sub(r"\1", text)
    text = _MD_TAG.sub("", text)
    text = _MD_ESCAPE.sub(r"\1", text)
    text = _MD_BLOCK_MARK.sub("", text)
    return _MD_INLINE_MARK.sub("", text)


class _VisibleText(html.parser.HTMLParser):
    _SKIPPED = frozenset({"script", "style", "noscript", "template"})

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._depth = 0

    @override
    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del attrs
        if tag in self._SKIPPED:
            self._depth += 1

    @override
    def handle_endtag(self, tag: str) -> None:
        if tag in self._SKIPPED and self._depth:
            self._depth -= 1

    @override
    def handle_data(self, data: str) -> None:
        if not self._depth:
            self.parts.append(data)


def html_text(raw_html: str) -> str:
    """The visible text of an HTML document: tags, scripts, and styles out,
    entities decoded, block boundaries as spaces."""
    parser = _VisibleText()
    parser.feed(raw_html)
    parser.close()
    return " ".join(parser.parts)


def squeeze(text: str) -> str:
    """Letters and digits alone: the sequence that survives every rendering."""
    return "".join(char for char in text if char.isalnum())


def quote_in_html(*, quote: str, raw_html: str, min_chars: int = 12) -> bool:
    """Whether a quote read from a markdown rendering is also in the page's
    visible text: a gate against a converter inventing words, never a proof.
    A squeezed quote shorter than ``min_chars`` fails, since a few letters
    match anywhere."""
    needle = squeeze(fold(markdown_plain(quote)))
    if len(needle) < min_chars:
        return False
    return needle in squeeze(fold(html_text(raw_html)))


__all__ = [
    "ArtifactStore",
    "Resliced",
    "fold",
    "html_text",
    "markdown_plain",
    "norm_map",
    "numbers_in",
    "quote_in_html",
    "reslice_quote",
    "sha256_of_text",
    "squeeze",
    "value_in_quote",
]
