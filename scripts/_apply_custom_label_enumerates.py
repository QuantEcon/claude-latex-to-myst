#!/usr/bin/env python3
r"""Flatten enumerates whose every ``\item`` carries an explicit
``[label]`` into labelled paragraphs (GH #111).

Pandoc's enumerate reader silently DROPS the optional arg of
``\item[(a)]``, renumbering the list 1..N — book-dp1's norm properties
(§1.2.1.2) render "1.–8." in HTML against the PDF's "(a)–(d)". A list
where **every** top-level ``\item`` has an explicit ``[…]`` arg (some
possibly empty — dp1's ``\item[] (nonnegativity)`` description-column
idiom) isn't an auto-counter list at all: the author chose the labels.
Markdown ordered lists can't carry non-numeric markers, so the closest
faithful form is blank-line-separated paragraphs, each opening with its
literal label text. The rewrite runs pre-pandoc; pandoc then converts
each paragraph's content (math, macros) normally and the labels survive
verbatim.

Conservative bails (the marker-preprocessor doctrine — pre-pandoc
passes can't see post-pandoc config, so bail on any shape not fully
modelled): any top-level ``\item`` without a ``[…]`` arg, a nested
list env inside the body, real content before the first ``\item``, or
an unclosed ``[`` → leave the whole enumerate for pandoc.

Usage:
    _apply_custom_label_enumerates.py TEX_FILE
"""

from __future__ import annotations

import re
import sys
from pathlib import Path


_ENUM_OPEN_RE = re.compile(r'\\begin\{enumerate\}(?:\[[^\]]*\])?')
_ENUM_CLOSE_RE = re.compile(r'\\end\{enumerate\}')
_NEST_RE = re.compile(r'\\begin\{(?:itemize|enumerate|description)\}')
_ITEM_RE = re.compile(r'\\item\b\s*')


def _iter_top_level_enumerates(text: str):
    """Yield ``(block_start, body_start, body_end, block_end)`` for each
    outermost enumerate, pairing begin/end by depth (mirrors
    ``_apply_enumerate_markers``, lesson 039)."""
    events = sorted(
        [(m.start(), m.end(), 'open') for m in _ENUM_OPEN_RE.finditer(text)]
        + [(m.start(), m.end(), 'close') for m in _ENUM_CLOSE_RE.finditer(text)]
    )
    depth = 0
    block_start = body_start = None
    for start, end, kind in events:
        if kind == 'open':
            if depth == 0:
                block_start, body_start = start, end
            depth += 1
        else:
            if depth == 0:
                continue
            depth -= 1
            if depth == 0 and block_start is not None:
                yield (block_start, body_start, start, end)
                block_start = body_start = None


def _starts_in_comment(text: str, pos: int) -> bool:
    """Same guard as the sibling preprocessors: skip a block whose
    ``\\begin`` sits on a ``%``-commented line."""
    line_start = text.rfind('\n', 0, pos) + 1
    i = line_start
    while i < pos:
        if text[i] == '\\':
            i += 2
            continue
        if text[i] == '%':
            return True
        i += 1
    return False


def parse_custom_label_items(body: str) -> list[tuple[str, str]] | None:
    """Parse an enumerate body into ``[(label, content), …]`` when every
    top-level ``\\item`` carries an explicit ``[…]`` arg. Returns
    ``None`` — leave the block to pandoc — on any bail condition.

    Labels in this idiom are short plain text (``(a)``, ``(b)``, or
    empty); a label containing ``]`` (e.g. nested optional-arg syntax)
    is not modelled and the simple ``find(']')`` would mis-split — but
    the leftover ``]…`` then rides into the content harmlessly, and no
    real corpus uses it.
    """
    if _NEST_RE.search(body):
        return None  # nested list env — not modelled
    # A ``%``-commented ``\item`` is not a boundary (Copilot review on
    # #136): treating it as one would split at the comment and emit its
    # text as a live paragraph — effectively uncommenting it. Filtered
    # out, the commented line rides inside the preceding item's content,
    # where pandoc's LaTeX reader drops the ``%`` comment correctly.
    item_matches = [
        m for m in _ITEM_RE.finditer(body)
        if not _starts_in_comment(body, m.start())
    ]
    if not item_matches:
        return None
    # Real content before the first \item (spacing tweaks like
    # \setlength would merely be dropped, but bail conservatively).
    head = body[: item_matches[0].start()]
    if any(
        ln.strip() and not ln.lstrip().startswith('%')
        for ln in head.split('\n')
    ):
        return None

    items: list[tuple[str, str]] = []
    for i, m in enumerate(item_matches):
        rest_start = m.end()
        if rest_start >= len(body) or body[rest_start] != '[':
            return None  # an item without [label] — auto-counter list
        close = body.find(']', rest_start)
        if close == -1:
            return None
        label = body[rest_start + 1 : close].strip()
        end = (
            item_matches[i + 1].start()
            if i + 1 < len(item_matches)
            else len(body)
        )
        content = body[close + 1 : end].strip()
        items.append((label, content))
    return items


def process_text(text: str) -> str:
    """Rewrite every all-custom-label enumerate into labelled paragraphs."""
    out: list[str] = []
    cursor = 0
    for block_start, body_start, body_end, block_end in _iter_top_level_enumerates(text):
        if block_start < cursor:
            continue
        if _starts_in_comment(text, block_start):
            continue
        items = parse_custom_label_items(text[body_start:body_end])
        if items is None:
            continue
        paragraphs = [
            f'{label} {content}'.strip() for label, content in items
        ]
        out.append(text[cursor:block_start])
        out.append('\n\n' + '\n\n'.join(paragraphs) + '\n\n')
        cursor = block_end
    out.append(text[cursor:])
    return ''.join(out)


def main() -> None:
    if len(sys.argv) != 2:
        sys.exit('usage: _apply_custom_label_enumerates.py TEX_FILE')
    tex_file = Path(sys.argv[1])
    text = tex_file.read_text(encoding='utf-8')
    new_text = process_text(text)
    if new_text != text:
        tex_file.write_text(new_text, encoding='utf-8')


if __name__ == '__main__':
    main()
