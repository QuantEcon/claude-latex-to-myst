#!/usr/bin/env python3
r"""Flatten enumerate/itemize lists whose every ``\item`` carries an
explicit ``[label]`` into labelled paragraphs (GH #111, #178).

Pandoc's list readers silently DROP the optional arg of ``\item[(a)]``:
an ``enumerate`` gets renumbered 1..N and an ``itemize`` collapses to
plain bullets — book-dp1's norm properties (§1.2.1.2) render "1.–8." in
HTML against the PDF's "(a)–(d)", and §8.3.2.1's fully-labelled itemize
of assumptions loses the ``(a)``–``(d)`` markers its prose then refers
back to (#178). A list where **every** top-level ``\item`` has an
explicit ``[…]`` arg (some possibly empty — dp1's ``\item[]
(nonnegativity)`` description-column idiom) isn't an auto-counter or
bullet list at all: the author chose the labels, and ``enumerate`` vs
``itemize`` is immaterial to that. Markdown lists can't carry arbitrary
non-numeric markers, so the closest faithful form is blank-line-
separated paragraphs, each opening with its literal label text. The
rewrite runs pre-pandoc; pandoc then converts each paragraph's content
(math, macros) normally and the labels survive verbatim.

Conservative bails (the marker-preprocessor doctrine — pre-pandoc
passes can't see post-pandoc config, so bail on any shape not fully
modelled): any top-level ``\item`` without a ``[…]`` arg, a nested
list env inside the body, real content before the first ``\item``, or
an unclosed ``[`` → leave the whole list for pandoc.

Usage:
    _apply_custom_label_enumerates.py TEX_FILE
"""

from __future__ import annotations

import re
import sys
from pathlib import Path


# Outer candidates are ``enumerate`` **and** ``itemize`` (#178): a fully
# manually-labelled list is not an auto-counter list regardless of which
# env opened it. Both accept an enumitem ``[…]`` option after the name.
# Pairing is by pure depth (any list open ++, any list close --); since
# LaTeX envs are properly nested/balanced, name-matching isn't needed to
# find the outermost block, and a genuinely nested list still bails via
# ``_NEST_RE`` in ``parse_custom_label_items``.
_LIST_OPEN_RE = re.compile(r'\\begin\{(?:enumerate|itemize)\}(?:\[[^\]]*\])?')
_LIST_CLOSE_RE = re.compile(r'\\end\{(?:enumerate|itemize)\}')
_NEST_RE = re.compile(r'\\begin\{(?:itemize|enumerate|description)\}')
_ITEM_RE = re.compile(r'\\item\b\s*')


def _iter_top_level_lists(text: str):
    """Yield ``(block_start, body_start, body_end, block_end)`` for each
    outermost enumerate/itemize, pairing begin/end by depth (mirrors
    ``_apply_enumerate_markers``, lesson 039). Tokens on ``%``-commented
    lines are not events (#138) — a commented ``\\end{…}`` would
    otherwise close the block early."""
    events = sorted(
        (start, end, kind)
        for start, end, kind in (
            [(m.start(), m.end(), 'open') for m in _LIST_OPEN_RE.finditer(text)]
            + [(m.start(), m.end(), 'close') for m in _LIST_CLOSE_RE.finditer(text)]
        )
        if not _starts_in_comment(text, start)
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


_LABEL_RE = re.compile(r'\\label\{([^}]*)\}')
_SETLENGTH_RE = re.compile(r'\\setlength\{[^}]*\}\{[^}]*\}')


def parse_custom_label_items(
    body: str,
) -> tuple[list[tuple[str, str]], list[str]] | None:
    """Parse an enumerate/itemize body into
    ``([(label, content), …], head_labels)`` when every top-level
    ``\\item`` carries an explicit ``[…]`` arg.
    ``head_labels`` are any ``\\label{}`` anchors that preceded the first
    ``\\item`` (hoisted out by the caller). Returns ``None`` — leave the
    block to pandoc — on any bail condition.

    Labels in this idiom are short plain text (``(a)``, ``(b)``, or
    empty); a label containing ``]`` (e.g. nested optional-arg syntax)
    is not modelled and the simple ``find(']')`` would mis-split — but
    the leftover ``]…`` then rides into the content harmlessly, and no
    real corpus uses it.
    """
    if any(
        not _starts_in_comment(body, m.start())
        for m in _NEST_RE.finditer(body)
    ):
        return None  # nested list env — not modelled (commented ones aren't real, #138)
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
    # Content before the first \item. A leading ``\label{}`` (e.g. dp2's
    # ``\begin{enumerate}\label{enum:b13}``) must not make the head-check
    # bail — that drops the block to pandoc, where convert_enumerate_style
    # then restyles the custom labels to (i),(ii),(iii) (#157A). Skip the
    # no-output tokens (``\label``, ``\setlength``, ``%``-comments) and
    # hoist any ``\label`` out as ``head_labels`` so its anchor survives;
    # bail only if genuine content remains.
    head = body[: item_matches[0].start()]
    head_live = '\n'.join(
        '' if ln.lstrip().startswith('%') else ln
        for ln in head.split('\n')
    )
    head_labels = _LABEL_RE.findall(head_live)
    residual = _SETLENGTH_RE.sub('', _LABEL_RE.sub('', head_live))
    if residual.strip():
        return None

    items: list[tuple[str, str]] = []
    for i, m in enumerate(item_matches):
        rest_start = m.end()
        if rest_start >= len(body) or body[rest_start] != '[':
            return None  # an item without [label] — auto-counter / bullet list
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
    return items, head_labels


def process_text(text: str) -> str:
    """Rewrite every all-custom-label enumerate/itemize into labelled
    paragraphs."""
    out: list[str] = []
    cursor = 0
    for block_start, body_start, body_end, block_end in _iter_top_level_lists(text):
        if block_start < cursor:
            continue
        if _starts_in_comment(text, block_start):
            continue
        parsed = parse_custom_label_items(text[body_start:body_end])
        if parsed is None:
            continue
        items, head_labels = parsed
        paragraphs = [
            f'{label} {content}'.strip() for label, content in items
        ]
        # Hoist a leading ``\label{}`` (anchor on the enumerate itself) onto
        # its own line ahead of the flattened paragraphs. Pandoc renders an
        # own-line ``\label`` as ``[]{#name …}``, which convert_standalone_labels
        # turns into a ``(name)=`` MyST target — so cross-refs to the list
        # still resolve (#157A).
        blocks = [f'\\label{{{lbl}}}' for lbl in head_labels] + paragraphs
        out.append(text[cursor:block_start])
        out.append('\n\n' + '\n\n'.join(blocks) + '\n\n')
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
