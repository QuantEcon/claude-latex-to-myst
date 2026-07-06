#!/usr/bin/env python3
"""Strip the render-only ``lstlisting`` options whose value is two or more
*adjacent* brace groups (``escapeinside={(*}{*)}``, ``literate={a}{b}1``)
before pandoc sees the source.

Pandoc's ``lstlisting`` option parser reads a key's value as a single
``{...}`` group. A value built from two or more adjacent brace groups
(``escapeinside={(*}{*)}``) derails the whole ``[...]`` option scan: the
closing ``]`` is never matched, so the entire option group survives and
leaks verbatim as the code block's first body line (issue #185). A
single-brace value (``caption={…}``, ``label={…}``, ``morekeywords={…}``)
parses cleanly and is left untouched.

The options this removes (``escapeinside``, ``literate``, ``moredelim`` …)
are PDF-rendering directives with no MyST equivalent, so dropping them is
loss-free for the converted ``{code-block}`` — the post-pandoc
``convert_pandoc_attr_code_blocks`` pass keeps ``caption`` / ``label`` /
``language`` and ignores the rest anyway.

This runs pre-pandoc (like the marker scripts) and is a no-op on sources
whose ``lstlisting`` blocks carry no brace-valued option. Conservative by
design: an unbalanced option group is left untouched.

Usage:
    _apply_lstlisting_options.py TEX_FILE
"""

import re
import sys
from pathlib import Path

# The ``[`` that opens the optional-argument group of a ``lstlisting``
# environment (whitespace between ``}`` and ``[`` is tolerated).
_OPEN_RE = re.compile(r'\\begin\{lstlisting\}[ \t]*\[')


def _starts_in_comment(text: str, pos: int) -> bool:
    """Return True if ``text[pos]`` sits in a LaTeX line-comment — i.e.
    the same physical line has an unescaped ``%`` before ``pos``.

    Other preprocessors in this repo treat commented-out source as a
    non-event; this pass follows suit so it never edits a
    ``%\\begin{lstlisting}[…]`` the author has commented out (and so the
    brace scan can't cross a ``%`` line boundary into live source — a
    contrived but real edge). Mirrors the guard in
    ``_apply_listing_markers._starts_in_comment``
    (FOLLOWUP-014-algorithm-parser-edge-cases.md, Gap A)."""
    line_start = text.rfind('\n', 0, pos) + 1
    i = line_start
    while i < pos:
        if text[i] == '\\':
            i += 2          # skip escaped char (including ``\%``)
            continue
        if text[i] == '%':
            return True
        i += 1
    return False


def _match_option_group(text: str, start: int) -> int | None:
    """``text[start]`` must be ``[``. Return the index just past the
    matching ``]`` (bracket-depth and brace-depth both back to 0), or
    ``None`` if the group is unbalanced or runs off the end.

    Brace- and bracket-aware so nested groups (``escapeinside={(*}{*)}``,
    ``moredelim=**[is][\\color{red}]``) don't fool the closer scan — this
    is exactly the balancing pandoc gets wrong."""
    depth_brace = 0
    depth_brack = 0
    i = start
    n = len(text)
    while i < n:
        c = text[i]
        if c == '\\':
            i += 2          # skip an escaped char (e.g. ``\%`` in escapechar)
            continue
        if c == '{':
            depth_brace += 1
        elif c == '}':
            depth_brace -= 1
        elif c == '[':
            depth_brack += 1
        elif c == ']':
            depth_brack -= 1
            if depth_brack == 0 and depth_brace == 0:
                return i + 1
        i += 1
    return None


def _split_top_level(opts: str) -> list[str]:
    """Split an option string on commas that sit at bracket- and
    brace-depth 0 — commas inside ``{…}`` / ``[…]`` are part of a value
    (``morekeywords={foo,bar}``) and must not split it."""
    parts: list[str] = []
    buf: list[str] = []
    depth_brace = depth_brack = 0
    i = 0
    n = len(opts)
    while i < n:
        c = opts[i]
        if c == '\\':
            buf.append(opts[i:i + 2])
            i += 2
            continue
        if c == '{':
            depth_brace += 1
        elif c == '}':
            depth_brace -= 1
        elif c == '[':
            depth_brack += 1
        elif c == ']':
            depth_brack -= 1
        if c == ',' and depth_brace == 0 and depth_brack == 0:
            parts.append(''.join(buf))
            buf = []
        else:
            buf.append(c)
        i += 1
    parts.append(''.join(buf))
    return parts


def _value_is_multi_brace(option: str) -> bool:
    """``True`` when ``option`` is ``key = {…}{…}…`` — a value whose head
    is two or more adjacent top-level brace groups. That is precisely the
    shape that breaks pandoc's key-value scan (``escapeinside``,
    ``literate``); a lone ``{…}`` value (``caption``, ``morekeywords``)
    returns ``False`` and is preserved."""
    m = re.match(r'\s*[A-Za-z@]+\s*=\s*', option)
    if not m:
        return False
    value = option[m.end():]
    groups = 0
    i = 0
    n = len(value)
    while i < n and value[i] == '{':
        depth = 0
        while i < n:
            if value[i] == '\\':
                i += 2
                continue
            if value[i] == '{':
                depth += 1
            elif value[i] == '}':
                depth -= 1
                if depth == 0:
                    i += 1
                    break
            i += 1
        groups += 1
        # ``literate`` permits whitespace between adjacent brace groups.
        while i < n and value[i] in ' \t':
            i += 1
    return groups >= 2


def _clean_option_group(opts: str) -> str:
    """Drop every option whose value is a multi-brace group, preserving the
    original comma/space spacing of the survivors."""
    kept = [o for o in _split_top_level(opts) if not _value_is_multi_brace(o)]
    return ','.join(kept)


def process_text(text: str) -> str:
    result: list[str] = []
    pos = 0
    for m in _OPEN_RE.finditer(text):
        if _starts_in_comment(text, m.start()):
            continue                          # commented-out block — non-event
        bracket_start = m.end() - 1          # index of the opening ``[``
        group_end = _match_option_group(text, bracket_start)
        if group_end is None:
            continue                          # unbalanced — leave untouched
        opts = text[bracket_start + 1:group_end - 1]
        cleaned = _clean_option_group(opts)
        if cleaned == opts:
            continue                          # nothing removed
        result.append(text[pos:bracket_start + 1])
        result.append(cleaned)
        result.append(']')
        pos = group_end
    result.append(text[pos:])
    return ''.join(result)


def main() -> None:
    if len(sys.argv) != 2:
        sys.exit('usage: _apply_lstlisting_options.py TEX_FILE')
    tex_file = Path(sys.argv[1])
    text = tex_file.read_text(encoding='utf-8')
    new_text = process_text(text)
    if new_text != text:
        tex_file.write_text(new_text, encoding='utf-8')


if __name__ == '__main__':
    main()
