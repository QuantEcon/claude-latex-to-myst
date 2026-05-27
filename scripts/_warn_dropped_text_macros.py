#!/usr/bin/env python3
"""Warn about text macros pandoc will silently drop.

Two families of macro produce the same end result — pandoc has no
handler, drops the macro along with its argument, and leaves broken
sentences scattered through the converted markdown:

1. **Project-defined text macros** (GH #22). Defined with
   ``\\DeclareUrlCommand`` or with a ``\\newcommand`` body that wraps
   ``#1`` in formatting macros pandoc doesn't know about. Scanned out
   of the source preamble(s).

2. **Package-imported text macros** (GH #50). Macros like ``\\ding{N}``
   from ``pifont`` or ``\\faIcon{X}`` from ``fontawesome`` that arrive
   via ``\\usepackage{}`` — no definition in user code to detect.
   Scanned by name against a curated registry of known-dropped macros.

Pandoc handles a fixed set of text commands natively (``\\textbf``,
``\\textit``, ``\\texttt``, ``\\emph``, ``\\textsf``, ``\\underline``,
…) — anything else is a candidate.

This pass detects both families, counts how many times each is used in
the converted chapter sources, and prints a single warning summary
recommending ``preprocess.rewrites`` rules the user can paste into
``config.yaml``. It does not modify any files — the actual rewrite is
opt-in per project.

Usage::

    _warn_dropped_text_macros.py SOURCE_DIR CHAPTER1.tex CHAPTER2.tex …
"""

from __future__ import annotations

import re
import sys
from collections import Counter
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


# ── Package-imported text macros (#50) ───────────────────────────────────────
#
# Macros that come from ``\usepackage{}`` imports — pandoc has no handler
# and silently drops the macro along with its argument. Unlike the
# ``\newcommand`` case above there is no definition to scan; detection is
# by macro name in the chapter body.
#
# The registry is intentionally small. Add entries as books surface them
# (the warning is paste-ready, so each new macro fixes itself once).
#
# Each entry: macro_name → {
#   'package':    LaTeX package the macro comes from (informational),
#   'has_arg':    True if ``\macro{ARG}`` form (vs. zero-arg ``\macro``),
#   'arg_glyphs': {arg_str: (unicode, label)} — replacements per arg
#                 (only meaningful when has_arg=True).
#   'replacement': (unicode, label) — fixed replacement (zero-arg only).
# }

_PACKAGE_DROP_REGISTRY: dict[str, dict] = {
    'ding': {
        'package': 'pifont',
        'has_arg': True,
        # Common pifont numbers seen in mathematical / data-science books.
        # Numbers correspond to ZapfDingbats glyph positions; the unicode
        # mappings here follow the pifont package manual.
        'arg_glyphs': {
            '51': ('✓', 'U+2713 check mark'),
            '52': ('✔', 'U+2714 heavy check mark'),
            '55': ('✗', 'U+2717 ballot x'),
            '56': ('✘', 'U+2718 heavy ballot x'),
            '108': ('●', 'U+25CF black circle'),
            '109': ('❍', 'U+274D shadowed white circle'),
        },
    },
    'faIcon': {
        'package': 'fontawesome5',
        'has_arg': True,
        # No defaults — too many icons; user picks per project.
        'arg_glyphs': {},
    },
    'faicon': {  # fontawesome (v4) lowercase variant
        'package': 'fontawesome',
        'has_arg': True,
        'arg_glyphs': {},
    },
    'checkmark': {  # amssymb / dingbat fallback
        'package': 'amssymb',
        'has_arg': False,
        'replacement': ('✓', 'U+2713 check mark'),
    },
}

# Match ``\macro{ARG}`` where ARG has no nested braces. The macros in
# the registry above all take simple one-token args by design.
def _package_arg_pattern(name: str) -> re.Pattern[str]:
    return re.compile(rf'\\{re.escape(name)}\s*\{{([^{{}}]*)\}}')


def _package_bare_pattern(name: str) -> re.Pattern[str]:
    # Word boundary: macro name not followed by a letter (so ``\ding`` doesn't
    # also match ``\dingbat``).
    return re.compile(rf'\\{re.escape(name)}(?![A-Za-z@])')


def find_package_macro_usages(text: str) -> dict[str, dict]:
    """Return ``{macro: {'count': N, 'arg_counts': Counter|None}}`` for
    every registered package-imported macro that appears in ``text``."""
    out: dict[str, dict] = {}
    for name, spec in _PACKAGE_DROP_REGISTRY.items():
        if spec['has_arg']:
            args = _package_arg_pattern(name).findall(text)
            if not args:
                continue
            out[name] = {'count': len(args), 'arg_counts': Counter(args)}
        else:
            n = len(_package_bare_pattern(name).findall(text))
            if n == 0:
                continue
            out[name] = {'count': n, 'arg_counts': None}
    return out


def scan_package_macros(chapter_files: list[Path]) -> dict[str, dict]:
    """Aggregate package-macro usage across chapters.

    Shape: ``{macro: {'count': N, 'arg_counts': Counter|None, 'files': [..]}}``.
    """
    out: dict[str, dict] = {}
    for ch in chapter_files:
        try:
            text = ch.read_text(encoding='utf-8', errors='replace')
        except OSError:
            continue
        found = find_package_macro_usages(text)
        for name, info in found.items():
            entry = out.setdefault(name, {
                'count': 0,
                'arg_counts': Counter() if info['arg_counts'] is not None else None,
                'files': [],
            })
            entry['count'] += info['count']
            entry['files'].append(ch.name)
            if info['arg_counts'] is not None:
                entry['arg_counts'].update(info['arg_counts'])
    return out


def format_package_warning(usage: dict[str, dict]) -> str:
    """Pretty-print package-macro usage + paste-ready rewrite suggestions."""
    if not usage:
        return ''
    lines = [
        '',
        'WARNING: package-imported text macros pandoc may drop silently:',
        '',
    ]
    suggested: list[str] = []  # paste-ready preprocess.rewrites entries
    manual: list[str] = []     # entries the user still has to fill in

    for macro, info in sorted(usage.items()):
        spec = _PACKAGE_DROP_REGISTRY[macro]
        pkg = spec.get('package') or 'unknown'
        files = ', '.join(sorted(set(info['files'])))
        lines.append(
            f"  \\{macro}  — used {info['count']}× (package `{pkg}`) "
            f"across {files}"
        )
        if spec['has_arg']:
            for arg, n in info['arg_counts'].most_common():
                glyph_info = spec.get('arg_glyphs', {}).get(arg)
                if glyph_info:
                    glyph, label = glyph_info
                    lines.append(
                        f"      \\{macro}{{{arg}}}: {n}× — suggested → "
                        f"{glyph}  ({label})"
                    )
                    suggested.append(
                        f"    - {{ from: '\\\\{macro}\\{{{re.escape(arg)}\\}}', "
                        f"to: '{glyph}' }}"
                    )
                else:
                    lines.append(
                        f"      \\{macro}{{{arg}}}: {n}× — no default; "
                        f"add a rewrite manually"
                    )
                    manual.append(
                        f"    # \\{macro}{{{arg}}} → choose replacement\n"
                        f"    # - {{ from: '\\\\{macro}\\{{{re.escape(arg)}\\}}',"
                        f" to: '???' }}"
                    )
        else:
            rep = spec.get('replacement')
            # Trailing guard: must match the detector's negative-lookahead
            # so the rewrite covers every counted occurrence. ``\b`` would
            # also block trailing digits (``\checkmark2``), so a usage we
            # detect wouldn't be rewritten — inconsistent. Lookahead only
            # blocks letters and ``@`` (the chars that can extend a macro
            # name).
            if rep:
                glyph, label = rep
                lines.append(f"      → {glyph}  ({label})")
                suggested.append(
                    f"    - {{ from: '\\\\{macro}(?![A-Za-z@])', "
                    f"to: '{glyph}' }}"
                )
            else:
                manual.append(
                    f"    # \\{macro} → choose replacement\n"
                    f"    # - {{ from: '\\\\{macro}(?![A-Za-z@])', "
                    f"to: '???' }}"
                )

    if suggested or manual:
        lines.extend([
            '',
            'To apply, add to config.yaml under preprocess.rewrites:',
            '',
        ])
        lines.extend(suggested)
        if manual:
            lines.append('')
            lines.extend(manual)
    lines.append('')
    return '\n'.join(lines)


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

    # (1) Custom macros defined in the preamble (#22).
    custom = scan(source_dir, chapter_files)
    msg = format_warning(custom)
    if msg:
        sys.stderr.write(msg)

    # (2) Package-imported macros pandoc silently drops (#50).
    pkg = scan_package_macros(chapter_files)
    pkg_msg = format_package_warning(pkg)
    if pkg_msg:
        sys.stderr.write(pkg_msg)


if __name__ == '__main__':
    main()
