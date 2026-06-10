"""Code-block transforms.

- ``convert_pandoc_attr_code_blocks``: handles ``\\begin{lstlisting}``
  shapes pandoc emits as ``\\`\\`\\` {#id .lang caption="..."}`` (closes #31).
- ``resolve_listings``: decodes minted ``<!--LISTING-...-->`` markers
  from the preprocess pass into ``{code-block}`` directives, slicing
  the referenced source file (lesson 015).

State coupling: ``resolve_listings`` reads
``postprocess._LISTING_SOURCE_BASE`` (set by ``apply_config`` from
``source_code_base`` in config.yaml). Late-imported at call time
to avoid circular-import at module load (P3a).
"""

from __future__ import annotations

import re
from pathlib import Path

from conversion_context import current_context
from ._helpers import convert_label_colons


def convert_pandoc_attr_code_blocks(text: str) -> str:
    """Convert pandoc-attribute fenced code blocks to MyST ``{code-block}``.

    Pandoc emits ``\\begin{lstlisting}[caption=…, label=lst:X]`` as a
    fenced code block whose info string is a pandoc attribute block::

        ``` {#lst:X .python caption="Foo" label="lst:X" language="Python"}
        body
        ```

    MyST does not honour pandoc's attribute syntax — it treats the
    whole ``{…}`` as the info string and drops it on the floor. The
    block renders as plain (anchorless) code and any ``\\ref{lst:X}``
    in body prose resolves to nothing.

    Convert any such block that carries an ``#id`` or a ``caption=…``
    into a MyST ``{code-block}`` directive with ``:name:`` /
    ``:caption:`` set; downgrade the rest to plain ``\\`\\`\\`lang``
    fences (closes #31).

    Detection guard: this pass must NOT match MyST's own directive
    fences (``\\`\\`\\`{code-block} python``). Pandoc always emits a
    space between the ``\\`\\`\\`\\`` and the ``{``; MyST directives
    do not. We use that to distinguish, plus a content-shape guard
    (pandoc attrs contain ``#``, ``.``, or ``=``; MyST directive
    names are single words).
    """
    # The attribute group must accept ``}`` inside quoted attribute
    # values (LaTeX caption text frequently contains ``\\texttt{Pi}``,
    # ``\\textbf{X}``, math fragments, etc. — each carries a literal
    # ``}``). Allow either a non-``}``/non-``"``/non-newline char, OR a
    # complete double-quoted string (where ``}`` is fair game inside
    # the quotes). The outer closing ``}`` is matched outside the
    # alternation, so it still terminates the attribute block
    # unambiguously (closes #35).
    fence_re = re.compile(
        r'^```[ \t]+\{'
        r'(?P<attrs>(?:[^}"\n]|"(?:[^"\\]|\\.)*")+)'
        r'\}[ \t]*\n'
        r'(?P<body>.*?)'
        r'^```\s*$',
        re.DOTALL | re.MULTILINE,
    )

    def parse_attrs(attr_str: str) -> dict:
        out = {'id': '', 'classes': [], 'kv': {}}
        i = 0
        while i < len(attr_str):
            if attr_str[i].isspace():
                i += 1
                continue
            if attr_str[i] == '#':
                m = re.match(r'#([^\s}]+)', attr_str[i:])
                if m:
                    out['id'] = m.group(1)
                    i += m.end()
                    continue
            if attr_str[i] == '.':
                m = re.match(r'\.([^\s}]+)', attr_str[i:])
                if m:
                    out['classes'].append(m.group(1))
                    i += m.end()
                    continue
            m = re.match(
                r'([a-zA-Z][a-zA-Z0-9_-]*)=("(?:[^"\\]|\\.)*"|[^\s}]+)',
                attr_str[i:],
            )
            if m:
                key = m.group(1)
                val = m.group(2)
                if val.startswith('"') and val.endswith('"'):
                    # Pandoc serialises ``"`` and ``\`` inside a quoted
                    # attribute value as ``\"`` and ``\\`` respectively
                    # (the regex above accepts those escape sequences).
                    # After stripping the outer quotes, decode the
                    # escapes — otherwise math captions like
                    # ``caption={$\alpha$}`` arrive here as ``$\\alpha$``
                    # and survive into MyST's ``:caption:`` field as
                    # doubled backslashes, which KaTeX then renders as
                    # "function with no arguments" errors (#71).
                    val = re.sub(r'\\(.)', r'\1', val[1:-1])
                out['kv'][key] = val
                i += m.end()
                continue
            i += 1  # unknown token — skip one char
        return out

    def replace(m: re.Match) -> str:
        attr_str = m.group('attrs')
        body = m.group('body')
        # Content-shape guard: must contain a pandoc-attr marker.
        if not re.search(r'[#.=]', attr_str):
            return m.group(0)
        attrs = parse_attrs(attr_str)
        label = attrs['id']
        caption = attrs['kv'].get('caption', '')
        lang = attrs['kv'].get('language', '').lower()
        if not lang and attrs['classes']:
            lang = attrs['classes'][0]
        if not lang:
            lang = 'text'

        body = body.rstrip('\n')

        if not label and not caption:
            # No semantic attrs to preserve — strip the attribute block
            # so MyST renders a normal fenced code block (rather than
            # treating the whole pandoc attrs as a broken info string).
            return f'```{lang}\n{body}\n```'

        lines = [f'```{{code-block}} {lang}']
        if label:
            lines.append(f':name: {convert_label_colons(label)}')
        if caption:
            caption = re.sub(r'\s+', ' ', caption).strip()
            lines.append(f':caption: {caption}')
        lines.append('')
        lines.append(body)
        lines.append('```')
        return '\n'.join(lines)

    return fence_re.sub(replace, text)


def resolve_listings(text: str, ctx=None) -> str:
    """Replace LISTING-START..LISTING-END markers with ``{code-block}`` directives.

    Marker format (emitted by _apply_listing_markers.py):

        <!--LISTING-START name=NAME lang=LANG path=PATH first=N last=M-->
        Caption text (possibly multi-line)
        <!--LISTING-END-->

    Pandoc may escape ``<`` to ``\\<`` and ``>`` to ``\\>``; the regex
    tolerates both forms. When the referenced source file is missing the
    directive is still emitted with a TODO comment in the body so the
    build does not fail.
    """
    ctx = ctx if ctx is not None else current_context()
    base: Path | None = ctx.listing_source_base

    pattern = re.compile(
        r'\\?<!--LISTING-START\s+'
        r'name=(?P<name>\S+)\s+'
        r'lang=(?P<lang>\S+)\s+'
        r'path=(?P<path>\S+)\s+'
        r'first=(?P<first>\d*)\s+'
        r'last=(?P<last>\d*)--\\?>'
        r'\s*(?P<caption>.*?)\s*'
        r'\\?<!--LISTING-END--\\?>',
        re.DOTALL,
    )

    def repl(m: re.Match) -> str:
        name = m.group('name')
        lang = m.group('lang') or 'text'
        path_raw = m.group('path')
        first = m.group('first')
        last = m.group('last')
        caption = re.sub(r'\s+', ' ', (m.group('caption') or '').strip())

        header = [f'```{{code-block}} {lang}']
        if name:
            header.append(f':name: {name}')
        if caption:
            header.append(f':caption: {caption}')
        header.append(':linenos:')
        header.append('')

        if base is None:
            # No source_code_base configured: emit the directive but mark the
            # body as needing manual insertion. Better than swallowing the
            # listing — users see the placeholder and can wire up the path.
            header.append(f'# TODO: source_code_base not configured; inline {path_raw}')
            header.append('```')
            return '\n'.join(header)

        src_path = (base / path_raw).resolve()
        if not src_path.is_file():
            header.append(f'# TODO: source not found: {path_raw}')
            header.append('```')
            return '\n'.join(header)

        try:
            lines = src_path.read_text(encoding='utf-8').splitlines()
        except UnicodeDecodeError:
            lines = src_path.read_text(encoding='latin-1').splitlines()

        f = int(first) if first else 1
        l = int(last) if last else len(lines)
        f = max(1, f)
        l = min(len(lines), l)
        snippet = '\n'.join(lines[f - 1 : l])

        header.append(snippet)
        header.append('```')
        return '\n'.join(header)

    return pattern.sub(repl, text)
