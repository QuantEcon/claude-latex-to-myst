#!/usr/bin/env python3
r"""Rewrite ``\begin{enumerate}...\end{enumerate}`` blocks whose every
``\\item`` carries an ``\\label{ex:...}`` into a sequence of EXERCISE
marker HTML comments. The post-pandoc resolver then decodes each
marker pair into a ``{exercise}`` directive with the original label.

Closes #69. The dominant LaTeX convention for textbook exercise lists
is::

    \\begin{enumerate}
    \\item\\label{ex:ch1:1} \\textbf{[Core] Backprop on a 2-layer net.} ...
    \\item\\label{ex:ch1:2} \\textbf{[Core] MSE vs. MLE.} ...
    \\end{enumerate}

Pandoc's enumerate parser converts each ``\\item`` to a numbered list
entry and **discards interior** ``\\label{}`` **calls** — they have
no place in pandoc's list AST. Any later ``{prf:ref}\`ex-ch1-1\``` (typically
in a solutions appendix back-link) then dangles because the anchor
never lands.

Surfaced in book-dp-deep-learning's R7 pass — 87 exercise labels in
source, 96 unresolved ``{prf:ref}`` in the build log (some chapter
bodies forward-reference the exercises too).

Marker format (single-line HTML comments so pandoc treats them as
self-contained blocks):

    <!--EXERCISE-START label=ex-ch1-1-->
    Item content (possibly multi-line markdown)
    <!--EXERCISE-END-->

The enumerate wrapper is **dissolved**: the ``\\begin{enumerate}`` and
``\\end{enumerate}`` are stripped, and the ``\\item`` tokens replaced
by the START markers. Pandoc converts the item content (between
markers) to markdown; the markers themselves pass through as raw
HTML comments. ``resolve_exercise_markers`` in ``transforms/envs.py``
decodes each pair to a ``{exercise}`` directive.

Conservative trigger: ONLY enumerates where every ``\\item`` opens
with ``\\label{ex:...}`` are rewritten. Mixed lists (some items
labelled, some not, or non-``ex:`` labels) are left for pandoc to
handle as ordinary bullets — the marker rewrite would otherwise
have to invent labels for unlabelled items, which masks editorial
mistakes (a missing label in the source).

Usage:
    _apply_enumerate_markers.py TEX_FILE
"""

from __future__ import annotations

import re
import sys
from pathlib import Path


# ``\begin{enumerate}`` with an optional ``[opts]`` arg (``[itemsep=4pt,
# leftmargin=*]`` is common in book sources).
_ENUM_RE = re.compile(
    r'\\begin\{enumerate\}(?:\[[^\]]*\])?(.*?)\\end\{enumerate\}',
    re.DOTALL,
)

# ``\item`` followed (with optional whitespace) by ``\label{ex:...}``.
# Captures the label name; the rest of the item body sits after the
# matched span.
_ITEM_LABELED_RE = re.compile(
    r'\\item\s*\\label\{(ex:[^}]+)\}'
)


def _starts_in_comment(text: str, pos: int) -> bool:
    """True when ``text[pos]`` sits on a LaTeX line-comment (same line
    has an unescaped ``%`` before ``pos``). Mirrors the helper in
    ``_apply_listing_markers.py``."""
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


def parse_enum_items(body: str) -> list[tuple[str, str]] | None:
    """Parse the body of an enumerate. Returns ``[(label, content), ...]``
    when every ``\\item`` carries an ``ex:``-prefixed ``\\label{}``;
    returns ``None`` otherwise (mixed / unlabelled enumerates are left
    alone)."""
    item_positions = [m.start() for m in re.finditer(r'\\item\b', body)]
    if not item_positions:
        return None

    items: list[tuple[str, str]] = []
    for i, start in enumerate(item_positions):
        end = item_positions[i + 1] if i + 1 < len(item_positions) else len(body)
        chunk = body[start:end]
        m = _ITEM_LABELED_RE.match(chunk)
        if not m:
            # An item without an ``ex:`` label disqualifies the whole
            # enumerate — leave it for pandoc to render as a normal
            # bullet list.
            return None
        label = m.group(1)
        content = chunk[m.end():].strip()
        items.append((label, content))
    return items


def emit_exercise_markers(items: list[tuple[str, str]]) -> str:
    """Render the parsed items as a sequence of ``<!--EXERCISE-START
    .. -->`` / ``<!--EXERCISE-END-->`` marker pairs separated by blank
    lines. The enumerate wrapper is gone — each item is now a
    free-standing block."""
    out_parts: list[str] = []
    for label, content in items:
        name = label.replace(':', '-')
        out_parts.append(
            f'<!--EXERCISE-START label={name}-->\n'
            f'{content}\n'
            f'<!--EXERCISE-END-->'
        )
    return '\n\n'.join(out_parts)


def process_text(text: str) -> str:
    """Rewrite every fully-``ex:``-labelled enumerate in ``text`` into
    marker form. Non-qualifying enumerates and comment-line blocks
    pass through unchanged."""

    def replace(m: re.Match) -> str:
        if _starts_in_comment(text, m.start()):
            return m.group(0)
        body = m.group(1)
        items = parse_enum_items(body)
        if items is None:
            return m.group(0)
        # Wrap with blank lines so the first marker is block-isolated
        # from any preceding paragraph and the last is separated from
        # following prose (mirrors the algorithm / listing / table
        # marker emit convention).
        return f'\n\n{emit_exercise_markers(items)}\n\n'

    return _ENUM_RE.sub(replace, text)


def main() -> None:
    if len(sys.argv) != 2:
        sys.exit('usage: _apply_enumerate_markers.py TEX_FILE')
    tex_file = Path(sys.argv[1])
    text = tex_file.read_text(encoding='utf-8')
    new_text = process_text(text)
    if new_text != text:
        tex_file.write_text(new_text, encoding='utf-8')


if __name__ == '__main__':
    main()
