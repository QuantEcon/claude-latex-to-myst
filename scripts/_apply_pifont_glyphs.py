#!/usr/bin/env python3
r"""Rewrite ``\ding{N}`` (pifont) to its unicode glyph in place (GH #159).

Pandoc has no handler for ``\ding`` and silently drops the macro with its
argument — a ``tabular`` whose data cells are ``\ding{51}`` checkmarks then
converts to a table of *blank* cells (book-dp2's ``tab:convergence_cases``,
Table 2.1, rendered empty). The ``\ding{N}``→unicode mapping is unambiguous
and lossless, so it is auto-applied here rather than left to per-book
``preprocess.rewrites`` (the warn path in ``_warn_dropped_text_macros.py``
only surfaces the *unmapped* args that remain).

Runs **before** the structural marker preprocessors (table/figure
extraction): once a cell's ``\ding{51}`` is base64-encoded into a marker
payload, the batch pandoc pass would drop it before the glyph could be
substituted.

Usage:
    _apply_pifont_glyphs.py TEX_FILE
"""

from __future__ import annotations

import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS_DIR))

from _warn_dropped_text_macros import apply_known_glyphs  # noqa: E402


def main() -> None:
    if len(sys.argv) != 2:
        sys.exit('usage: _apply_pifont_glyphs.py TEX_FILE')
    tex_file = Path(sys.argv[1])
    text = tex_file.read_text(encoding='utf-8')
    new_text = apply_known_glyphs(text)
    if new_text != text:
        tex_file.write_text(new_text, encoding='utf-8')


if __name__ == '__main__':
    main()
