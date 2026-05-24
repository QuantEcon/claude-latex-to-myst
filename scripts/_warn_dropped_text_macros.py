#!/usr/bin/env python3
"""Warn about custom text macros pandoc will silently drop.

Pandoc handles a fixed set of text commands natively (``\\textbf``,
``\\textit``, ``\\texttt``, ``\\emph``, ``\\textsf``, ``\\underline``,
…). Project-specific text macros — defined with ``\\DeclareUrlCommand``
or with a ``\\newcommand`` body that wraps ``#1`` in formatting macros
pandoc doesn't know about — are dropped silently *along with their
argument*, leaving broken sentences scattered through the converted
markdown.

This pass scans the source LaTeX for those definitions, counts how
many times each is used in the converted chapter sources, and prints
a single warning summary recommending a ``preprocess.rewrites`` rule
the user can paste into their ``config.yaml``. It does not modify any
files — the actual rewrite is opt-in per project (GH #22).

Usage::

    _warn_dropped_text_macros.py SOURCE_DIR CHAPTER1.tex CHAPTER2.tex …
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

# Pandoc natively converts these text commands. Anything else is a
# candidate for silent drop.
_PANDOC_NATIVE_TEXT_CMDS = frozenset({
    'textbf', 'textit', 'texttt', 'emph', 'textsf', 'textrm',
    'textnormal', 'textsc', 'textup', 'textsl', 'underline',
})

# Patterns that pick up macro definitions from a .tex preamble or body.
# Header-only — the body is balanced separately via ``_match_braced``
# because newcommand bodies routinely nest 3+ braces (e.g.
# ``\textcolor{red}{\textbf{#1}}``) and a single-regex match for that
# depth becomes unreadable.
_DECLARE_URL_RE = re.compile(r'\\DeclareUrlCommand\s*\\([A-Za-z@]+)\s*\{([^}]*)\}')
_NEWCOMMAND_HEAD_RE = re.compile(
    r'\\(?:re)?newcommand\s*\{?\s*\\([A-Za-z@]+)\s*\}?'
    r'\s*(?:\[(\d+)\])?'
    r'\s*\{'
)


def _match_braced(text: str, open_pos: int) -> int:
    """Return the index *after* the ``}`` that closes the brace whose
    opening ``{`` sits at ``open_pos``. ``-1`` if unbalanced."""
    depth = 1
    i = open_pos + 1
    while i < len(text):
        c = text[i]
        if c == '\\' and i + 1 < len(text):
            i += 2
            continue
        if c == '{':
            depth += 1
        elif c == '}':
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    return -1


def _iter_newcommands(text: str):
    """Yield ``(name, nargs, body, start, end)`` for every
    ``\\newcommand``/``\\renewcommand`` in ``text``."""
    for m in _NEWCOMMAND_HEAD_RE.finditer(text):
        open_brace = m.end() - 1  # the ``{`` that starts the body
        close = _match_braced(text, open_brace)
        if close < 0:
            continue
        body = text[open_brace + 1:close - 1]
        nargs = int(m.group(2) or '0')
        yield m.group(1), nargs, body, m.start(), close


def _suggest_replacement(body: str) -> str:
    """Pick the nearest pandoc-native equivalent for a custom macro's
    body. The styling may be lossy (colour, URL-break-points are lost)
    but the *content* survives, which is the whole point of the
    rewrite suggestion."""
    if r'\textbf' in body or r'\textcolor' in body:
        return r'\textbf'
    if r'\texttt' in body or r'\url' in body or r'\path' in body \
            or r'urlstyle{tt}' in body:
        return r'\texttt'
    if r'\textit' in body or r'\emph' in body or r'\textsl' in body:
        return r'\emph'
    if r'\textsf' in body:
        return r'\textsf'
    return r'\texttt'  # safest default for an "inline identifier" shape


def find_custom_text_macros(text: str) -> dict[str, str]:
    """Return ``{macro_name: suggested_replacement}`` for every custom
    text macro defined in ``text``. Math-only macros (no ``#1`` in
    body) are skipped — they're not used as ``\\X{arg}`` and pandoc
    handles them differently."""
    found: dict[str, str] = {}

    for m in _DECLARE_URL_RE.finditer(text):
        name = m.group(1)
        # \DeclareUrlCommand is by definition a one-argument URL-style
        # macro. Pandoc has no handler for it, so always flag.
        found[name] = _suggest_replacement(m.group(2))

    for name, nargs, body, _start, _end in _iter_newcommands(text):
        if nargs < 1 or '#1' not in body:
            continue  # math-only or zero-arg macro — out of scope
        if name in _PANDOC_NATIVE_TEXT_CMDS:
            continue  # user redefined a built-in; let pandoc handle it
        # Only flag if the body uses *text* formatting — math macros
        # like ``\newcommand{\norm}[1]{\|#1\|}`` are handled inside
        # math mode and don't suffer the drop.
        if not re.search(
            r'\\(text\w+|emph|underline|textcolor|url|path|href)\b',
            body,
        ):
            continue
        found[name] = _suggest_replacement(body)

    return found


def count_usages(text: str, macro: str) -> int:
    """Count occurrences of ``\\macro{…}`` (with an argument) in
    ``text``. Definitions are skipped so a macro that's defined but
    never called doesn't trigger the warning."""
    # Strip the definitions first so we don't double-count them.
    text = _DECLARE_URL_RE.sub('', text)
    # Walk \newcommand spans and cut them out by index range.
    cuts = sorted(
        ((s, e) for _n, _a, _b, s, e in _iter_newcommands(text)),
        reverse=True,
    )
    for s, e in cuts:
        text = text[:s] + text[e:]
    return len(re.findall(rf'\\{re.escape(macro)}\s*\{{', text))


def scan(source_dir: Path, chapter_files: list[Path]) -> dict[str, dict]:
    """Build ``{macro: {'suggest': X, 'count': N, 'files': [..]}}``
    across the project. Definitions are sourced from every ``.tex``
    under ``source_dir`` (preambles often live in a main file or a
    shared ``preamble.tex`` rather than the chapter file itself)."""
    defs: dict[str, str] = {}
    for tex in source_dir.glob('*.tex'):
        try:
            text = tex.read_text(encoding='utf-8', errors='replace')
        except OSError:
            continue
        defs.update(find_custom_text_macros(text))

    if not defs:
        return {}

    usage: dict[str, dict] = {}
    for ch in chapter_files:
        try:
            body = ch.read_text(encoding='utf-8', errors='replace')
        except OSError:
            continue
        for macro, suggest in defs.items():
            n = count_usages(body, macro)
            if n <= 0:
                continue
            entry = usage.setdefault(
                macro, {'suggest': suggest, 'count': 0, 'files': []}
            )
            entry['count'] += n
            entry['files'].append(ch.name)
    return usage


def format_warning(usage: dict[str, dict]) -> str:
    if not usage:
        return ''
    lines = [
        '',
        'WARNING: custom text macros pandoc may drop silently:',
        '',
    ]
    for macro, info in sorted(usage.items()):
        files = ', '.join(sorted(set(info['files'])))
        lines.append(
            f"  \\{macro}  — used {info['count']}× across {files}"
        )
        lines.append(
            f"      suggested rewrite: \\{macro}{{…}} → "
            f"{info['suggest']}{{…}}"
        )
    lines.extend([
        '',
        'To apply, add to config.yaml under preprocess.rewrites:',
        '',
    ])
    for macro, info in sorted(usage.items()):
        target = info['suggest']
        lines.append(
            f"    - {{ from: '\\\\{macro}\\{{((?:\\\\.|[^{{}}])*)\\}}',"
        )
        lines.append(
            f"        to:   '{target}{{\\1}}' }}"
        )
    lines.append('')
    return '\n'.join(lines)


def main() -> None:
    if len(sys.argv) < 3:
        sys.exit(
            'usage: _warn_dropped_text_macros.py SOURCE_DIR CHAPTER.tex …'
        )
    source_dir = Path(sys.argv[1])
    chapter_files = [Path(p) for p in sys.argv[2:]]
    usage = scan(source_dir, chapter_files)
    msg = format_warning(usage)
    if msg:
        sys.stderr.write(msg)


if __name__ == '__main__':
    main()
