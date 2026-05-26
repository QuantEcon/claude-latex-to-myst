#!/usr/bin/env python3
"""Rewrite \\begin{algorithm}...\\end{algorithm} (algorithm2e) blocks in a .tex
file into ALGORITHM marker HTML comments that pandoc passes through verbatim
and postprocess.py later expands into ``{prf:algorithm}`` directives.

Marker format:

    <!--ALGORITHM name=algo-foo title=Title body=BASE64BODY-->

The body is base64-encoded because pandoc would otherwise mangle ``\\;``
statement terminators and reformat ``\\While`` / ``\\Repeat`` etc.

This is the Python port of dp1's ``_rewrite_algorithms.pl`` (lesson 009: no
Perl in this pipeline).

Usage:
    _apply_algorithm_markers.py TEX_FILE
"""

import base64
import re
import sys
from pathlib import Path


def _find_balanced_end(s: str, start: int, open_ch: str, close_ch: str) -> int:
    """Given s[start] == open_ch, return index of the matching close_ch (inclusive).

    Returns -1 if unbalanced.
    """
    if start >= len(s) or s[start] != open_ch:
        return -1
    depth = 0
    i = start
    while i < len(s):
        c = s[i]
        if c == open_ch:
            depth += 1
        elif c == close_ch:
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return -1


def _extract_caption(body: str) -> tuple[str, str, str]:
    """Strip the last ``\\caption{...}`` from the body and return
    ``(stripped_body, label, title)``. Either label or title may be empty.

    Recognises four layouts:
        \\caption{\\label{algo:foo} Title}                                 # label inside caption (#39)
        ... body ... \\caption{Title} \\label{algo:foo}                     # caption+label trailing (#39)
        \\caption{Title} \\label{algo:foo} \\begin{algorithmic} ... body    # caption+label leading (#43)
        \\label{algo:foo} ... body ... \\caption{Title}                     # label before caption
    """
    label = ''
    title = ''

    last_idx = body.rfind('\\caption{')
    pre_caption = body if last_idx == -1 else body[:last_idx]
    post_caption = ''

    if last_idx != -1:
        brace_open = last_idx + len('\\caption')
        brace_close = _find_balanced_end(body, brace_open, '{', '}')
        if brace_close == -1:
            return body.rstrip(), label, title

        post_caption = body[brace_close + 1 :]
        inner = body[brace_open + 1 : brace_close]

        # Inside-caption label takes precedence (deterministic when both forms exist).
        m = re.match(r'\s*\\label\{([^}]+)\}\s*(.*)\s*$', inner, re.DOTALL)
        if m:
            label = m.group(1)
            title = m.group(2)
        else:
            title = inner
        title = re.sub(r'\s+', ' ', title).strip()

    # Fallback: scan post_caption first (caption+label-leading shape from #43),
    # then pre_caption (label-before-caption shape, or label without caption).
    if not label:
        for region_name in ('post', 'pre'):
            region = post_caption if region_name == 'post' else pre_caption
            m = re.search(r'\\label\{([^}]+)\}', region)
            if m:
                label = m.group(1)
                stripped_region = region[:m.start()] + region[m.end():]
                if region_name == 'post':
                    post_caption = stripped_region
                else:
                    pre_caption = stripped_region
                break

    stripped = (pre_caption + post_caption).rstrip()
    return stripped, label, title


def rewrite_algorithm(body: str, auto_name_fn) -> str:
    """Return the marker replacement for one algorithm body."""
    stripped, label, title = _extract_caption(body)

    name = label or auto_name_fn()
    # MyST labels use hyphens, not colons.
    name_my = name.replace(':', '-')

    # Trim and base64-encode the body.
    stripped = stripped.strip()
    b64 = base64.b64encode(stripped.encode('utf-8')).decode('ascii')

    return f'\n\n<!--ALGORITHM name={name_my} title={title} body={b64}-->\n\n'


def _starts_in_comment(text: str, pos: int) -> bool:
    """True iff ``text[pos]`` is inside a LaTeX line-comment.

    Same guard as in ``_apply_listing_markers.py``: a ``\\begin{algorithm}``
    on a line that's been commented out with ``%`` should be left alone
    (else the END marker on a fresh line of the replacement loses its
    ``%`` and leaks into pandoc's output).
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


def process_text(text: str, auto_prefix: str) -> str:
    """Replace every ``\\begin{algorithm}...\\end{algorithm}`` block with a
    marker. Auto-generates labels (using ``auto_prefix``) for blocks without a
    caption/label so cross-references can still target them.
    """
    counter = {'n': 0}

    def next_auto_name() -> str:
        counter['n'] += 1
        return f'algo:{auto_prefix}-auto-{counter["n"]}'

    pattern = re.compile(
        r'\\begin\{algorithm\}(?:\[[^\]]*\])?(.*?)\\end\{algorithm\}',
        re.DOTALL,
    )

    def repl(m: re.Match) -> str:
        if _starts_in_comment(text, m.start()):
            return m.group(0)
        return rewrite_algorithm(m.group(1), next_auto_name)

    return pattern.sub(repl, text)


def main() -> None:
    if len(sys.argv) != 2:
        sys.exit('usage: _apply_algorithm_markers.py TEX_FILE')

    tex_file = Path(sys.argv[1])
    text = tex_file.read_text(encoding='utf-8')

    # Auto-prefix mirrors dp1: filename stem with leading ``ch_`` stripped.
    stem = tex_file.stem
    auto_prefix = stem[3:] if stem.startswith('ch_') else stem

    new_text = process_text(text, auto_prefix)
    if new_text != text:
        tex_file.write_text(new_text, encoding='utf-8')


if __name__ == '__main__':
    main()
