#!/usr/bin/env python3
"""Rewrite standalone ``\\begin{algorithmic}...\\end{algorithmic}`` blocks
into ALGORITHMIC marker HTML comments that pandoc passes through
verbatim and ``postprocess.resolve_algorithmics`` later expands into
Markdown bullet lists.

Marker format::

    <!--ALGORITHMIC body=BASE64BODY-->

The body is base64-encoded so pandoc passes the algpseudocode keywords
(``\\STATE``, ``\\FOR``, ``\\IF``, ``\\REPEAT``, …) through unchanged —
otherwise pandoc reads them as unknown LaTeX commands and may reflow or
drop the body.

**Scope:** this preprocessor only rewrites ``algorithmic`` blocks that
are NOT already inside a ``\\begin{algorithm}…\\end{algorithm}`` wrapper
— those are handled by ``_apply_algorithm_markers.py`` (which has run
before this script and already encoded its bodies). The standalone
pattern shows up when authors use a custom wrapper like
``definitionbox`` (a tcolorbox) or place pseudocode inline.

Same sentinel pattern as algorithm2e (lesson 014) and description envs
(lesson 022); see GH #20 for the algpseudocode dialect specifics.

Usage:
    _apply_algorithmic_markers.py TEX_FILE
"""

import base64
import re
import sys
from pathlib import Path


def _starts_in_comment(text: str, pos: int) -> bool:
    """True iff ``text[pos]`` is inside a LaTeX line-comment."""
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


def process_text(text: str) -> str:
    """Replace every ``\\begin{algorithmic}…\\end{algorithmic}`` block
    with an ALGORITHMIC marker. The optional ``[opts]`` after
    ``algorithmic`` (the line-numbering style, e.g. ``[1]``) is stripped.
    """
    pattern = re.compile(
        r'\\begin\{algorithmic\}(?:\[[^\]]*\])?(.*?)\\end\{algorithmic\}',
        re.DOTALL,
    )

    def repl(m: re.Match) -> str:
        if _starts_in_comment(text, m.start()):
            return m.group(0)
        body = m.group(1).strip()
        b64 = base64.b64encode(body.encode('utf-8')).decode('ascii')
        return f'\n\n<!--ALGORITHMIC body={b64}-->\n\n'

    return pattern.sub(repl, text)


def main() -> None:
    if len(sys.argv) != 2:
        sys.exit('usage: _apply_algorithmic_markers.py TEX_FILE')

    tex_file = Path(sys.argv[1])
    text = tex_file.read_text(encoding='utf-8')
    new_text = process_text(text)
    if new_text != text:
        tex_file.write_text(new_text, encoding='utf-8')


if __name__ == '__main__':
    main()
