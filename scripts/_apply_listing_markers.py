#!/usr/bin/env python3
"""Rewrite ``\\begin{listing}...\\end{listing}`` (minted) blocks in a .tex
file into LISTING marker HTML comments that pandoc passes through verbatim.
postprocess.py then reads the referenced source file, slices the requested
line range, and emits a MyST ``code-block`` directive.

Marker format:

    <!--LISTING-START name=NAME lang=LANG path=PATH first=N last=M-->
    Caption text (possibly multi-line)
    <!--LISTING-END-->

This is the Python port of dp1's ``_rewrite_listings.pl`` (lesson 009: no
Perl in this pipeline).

Usage:
    _apply_listing_markers.py TEX_FILE
"""

import re
import sys
from pathlib import Path


def rewrite_listing(body: str) -> str:
    """Return the marker replacement for one listing body."""
    opts, lang, path = '', 'text', ''
    m = re.search(
        r'\\inputminted(?:\[([^\]]*)\])?\{([^}]*)\}\{([^}]*)\}',
        body,
    )
    if m:
        opts = m.group(1) or ''
        lang = m.group(2) or 'text'
        path = m.group(3) or ''

    first_m = re.search(r'firstline=(\d+)', opts)
    last_m = re.search(r'lastline=(\d+)', opts)
    first = first_m.group(1) if first_m else ''
    last = last_m.group(1) if last_m else ''

    label, caption = '', ''
    # ``\caption{\label{...} caption text}`` at end of body — match the dp1
    # pattern. ``[^}]+`` is fine for the label (labels never contain braces);
    # ``.*?`` (non-greedy, DOTALL) handles multi-line captions.
    cap_m = re.search(
        r'\\caption\{\s*\\label\{([^}]+)\}\s*(.*?)\}\s*\Z',
        body,
        re.DOTALL,
    )
    if cap_m:
        label = cap_m.group(1)
        caption = cap_m.group(2)

    name = label.replace(':', '-')
    caption = re.sub(r'\s+', ' ', caption).strip()

    return (
        f'<!--LISTING-START name={name} lang={lang} path={path} '
        f'first={first} last={last}-->\n{caption}\n<!--LISTING-END-->'
    )


def process_text(text: str) -> str:
    pattern = re.compile(
        r'\\begin\{listing\}(?:\[[^\]]*\])?(.*?)\\end\{listing\}',
        re.DOTALL,
    )
    return pattern.sub(lambda m: rewrite_listing(m.group(1)), text)


def main() -> None:
    if len(sys.argv) != 2:
        sys.exit('usage: _apply_listing_markers.py TEX_FILE')
    tex_file = Path(sys.argv[1])
    text = tex_file.read_text(encoding='utf-8')
    new_text = process_text(text)
    if new_text != text:
        tex_file.write_text(new_text, encoding='utf-8')


if __name__ == '__main__':
    main()
