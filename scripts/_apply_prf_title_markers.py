#!/usr/bin/env python3
"""Preserve the optional ``[title]`` of theorem-family environments.

Pandoc **drops** the optional argument of a ``\\begin{theorem}[Title]`` it
doesn't recognise (no matching ``\\newtheorem`` in scope), so the title is lost
before postprocess ever sees it (issue #112). For ``\\begin{proof}[Proof of …]``
pandoc instead renders the title *inline* (``*Proof of ….*``) which then
duplicates sphinx-proof's own auto heading.

This pre-pandoc pass moves the optional title out of the ``[...]`` slot and into
a ``<!--PRFTITLE-START-->Title<!--PRFTITLE-END-->`` marker on the first body
line. Pandoc passes the comment delimiters through verbatim (escaping the
angle brackets) **and** converts the title text between them — so any ``\\ref``
/ math in a title becomes proper markdown. ``transforms.envs`` then lifts the
marker content onto the ``{prf:*}`` directive argument. Removing the ``[...]``
also stops pandoc rendering the proof title inline, killing the duplication.

Conservative + purely syntactic (the marker-boundary rule): it only fires on a
fixed theorem-family env list (plus any ``extra_environments`` mapping to
``prf:*`` from the config) and only when an optional ``[...]`` directly follows
``\\begin{env}`` on the same line.

Usage:
    _apply_prf_title_markers.py CONFIG_PATH TEX_FILE
    _apply_prf_title_markers.py TEX_FILE
"""

import re
import sys
from pathlib import Path

# Standard theorem-family environments that take an optional ``[title]`` and
# map to a ``prf:*`` directive. Mirrors the prf half of
# ``conversion_context.DEFAULT_ENV_MAP``. ``algorithm`` is excluded — its
# optional arg is handled by ``_apply_algorithm_markers.py``.
_DEFAULT_PRF_ENVS = (
    'theorem', 'boxtheorem',
    'lemma',
    'proof',
    'definition', 'boxdefinition',
    'proposition', 'boxproposition',
    'corollary', 'boxcorollary',
    'example',
    'remark',
    'assumption',
)

START = '<!--PRFTITLE-START-->'
END = '<!--PRFTITLE-END-->'


def _find_optional_arg_end(s: str, start: int) -> int:
    """Given ``s[start] == '['``, return the index of the matching ``]``.

    Brackets nested inside ``{...}`` groups don't close the optional arg
    (e.g. ``[Proof of \\ref{x[y]}]``). Returns -1 if unbalanced.
    """
    depth = 0
    brace = 0
    i = start
    while i < len(s):
        c = s[i]
        if c == '{':
            brace += 1
        elif c == '}':
            brace -= 1
        elif brace == 0:
            if c == '[':
                depth += 1
            elif c == ']':
                depth -= 1
                if depth == 0:
                    return i
        i += 1
    return -1


def _prf_envs_from_config(config_path: Path) -> tuple[str, ...]:
    try:
        from _config import load
        config = load(config_path)
    except Exception:
        return _DEFAULT_PRF_ENVS
    extra = (config or {}).get('extra_environments') or {}
    names = set(_DEFAULT_PRF_ENVS)
    for env, directive in extra.items():
        if isinstance(directive, str) and directive.startswith('prf:') \
                and directive != 'prf:algorithm':
            names.add(env)
    return tuple(sorted(names))


def apply_markers(text: str, envs: tuple[str, ...]) -> str:
    alt = '|'.join(re.escape(e) for e in envs)
    # ``\begin{env}`` optionally followed (same line) by ``[`` — the optional
    # title slot. ``[^\S\n]*`` allows spaces but not a newline between them.
    begin_re = re.compile(rf'\\begin\{{({alt})\}}[^\S\n]*(?=\[)')

    out = []
    pos = 0
    for m in begin_re.finditer(text):
        bracket = m.end()  # index of the '['
        close = _find_optional_arg_end(text, bracket)
        if close < 0:
            continue
        title = text[bracket + 1:close].strip()
        out.append(text[pos:m.end()])          # up to (not incl.) the '['
        # Drop the ``[title]``; keep whatever follows on the line (e.g.
        # ``\label{…}``) intact, then inject the marker on a fresh line.
        rest_start = close + 1
        # Find end of the begin line so the marker lands inside the env body.
        nl = text.find('\n', rest_start)
        if nl < 0:
            nl = len(text)
        line_tail = text[rest_start:nl]
        out.append(f'{line_tail}\n{START}{title}{END}')
        pos = nl
    out.append(text[pos:])
    return ''.join(out)


def main() -> None:
    args = sys.argv[1:]
    if len(args) == 2:
        config_path, tex_path = Path(args[0]), Path(args[1])
        envs = _prf_envs_from_config(config_path)
    elif len(args) == 1:
        tex_path = Path(args[0])
        envs = _DEFAULT_PRF_ENVS
    else:
        sys.exit('usage: _apply_prf_title_markers.py [CONFIG] TEX_FILE')

    text = tex_path.read_text()
    tex_path.write_text(apply_markers(text, envs))


if __name__ == '__main__':
    main()
