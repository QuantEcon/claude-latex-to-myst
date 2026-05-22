#!/usr/bin/env python3
"""Rewrite ``\\begin{description}...\\end{description}`` blocks in a .tex
file into DESCRIPTION marker HTML comments that pandoc passes through
verbatim and ``postprocess.convert_description_lists`` later expands
into MyST definition-list syntax (``Term\\n: body``).

Marker format::

    <!--DESCRIPTION-START-->

    <!--DESCITEM term=BASE64TERM-->

    body content for item 1...

    <!--DESCITEM term=BASE64TERM-->

    body content for item 2...

    <!--DESCRIPTION-END-->

Pandoc otherwise drops the ``\\item[Term]`` labels entirely on
LaTeX→Markdown, leaving a paragraph soup of definitions with no terms
attached (GH #19). Term labels are base64-encoded so they can contain
arbitrary characters (``]``, ``{}``, inline math) without the marker
parser needing to know about LaTeX escaping.

Usage:
    _apply_description_markers.py TEX_FILE
"""

import base64
import re
import sys
from pathlib import Path


_ITEM_RE = re.compile(r'\\item\s*(?:\[([^\]]*)\])?\s*', re.DOTALL)


def _starts_in_comment(text: str, pos: int) -> bool:
    """Same guard as the algorithm + listing preprocessors: a
    ``\\begin{description}`` on a line that's been commented out with
    ``%`` should be left alone (else the END marker on a fresh line of
    the replacement loses its ``%`` and leaks into pandoc's output).
    """
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


def _split_items(body: str) -> list[tuple[str, str]]:
    """Split a description-env body into ``[(term, body), ...]``.

    ``term`` is the literal text from the ``\\item[…]`` optional arg
    (empty string if absent). ``body`` is the text that follows the
    item up to the next ``\\item`` (or end of body).
    """
    items: list[tuple[str, str]] = []
    matches = list(_ITEM_RE.finditer(body))
    for idx, m in enumerate(matches):
        term = (m.group(1) or '').strip()
        body_start = m.end()
        body_end = matches[idx + 1].start() if idx + 1 < len(matches) else len(body)
        items.append((term, body[body_start:body_end].strip()))
    return items


def rewrite_description(body: str) -> str:
    """Return the marker-replacement string for one description body."""
    items = _split_items(body)
    if not items:
        # No \item inside — leave the env intact for human inspection.
        return f'\\begin{{description}}{body}\\end{{description}}'

    parts = ['\n\n<!--DESCRIPTION-START-->\n']
    for term, item_body in items:
        b64 = base64.b64encode(term.encode('utf-8')).decode('ascii')
        parts.append(f'\n<!--DESCITEM term={b64}-->\n\n{item_body}\n')
    parts.append('\n<!--DESCRIPTION-END-->\n\n')
    return ''.join(parts)


def process_text(text: str) -> str:
    """Replace every ``\\begin{description}...\\end{description}`` block
    with the marker form. The optional ``[opts]`` after ``description``
    (e.g. ``[itemsep=3pt, leftmargin=1.4em]``) is stripped — formatting
    options have no MyST analogue.
    """
    pattern = re.compile(
        r'\\begin\{description\}(?:\[[^\]]*\])?(.*?)\\end\{description\}',
        re.DOTALL,
    )

    def repl(m: re.Match) -> str:
        if _starts_in_comment(text, m.start()):
            return m.group(0)
        return rewrite_description(m.group(1))

    return pattern.sub(repl, text)


def main() -> None:
    if len(sys.argv) != 2:
        sys.exit('usage: _apply_description_markers.py TEX_FILE')

    tex_file = Path(sys.argv[1])
    text = tex_file.read_text(encoding='utf-8')
    new_text = process_text(text)
    if new_text != text:
        tex_file.write_text(new_text, encoding='utf-8')


if __name__ == '__main__':
    main()
