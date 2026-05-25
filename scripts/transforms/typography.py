"""Text-cleanup transforms: pandoc artifact strips, TeX residues,
whitespace compression, epigraph blocks.

None of these touch cross-references or math — they're pure
text-level cleanup that can run independently of the rest of the
pipeline.
"""

from __future__ import annotations

import re


def strip_pandoc_html_separators(text: str) -> str:
    r"""Strip pandoc's empty-HTML-comment lexer-defeat artifacts.

    Pandoc inserts ``\`<!-- -->\`{=html}`` between adjacent inline
    elements when it needs to keep CommonMark's lexer from
    greedy-merging the surrounding tokens — typically between an
    inline ``$math$`` and a following digit, or between two adjacent
    code spans (``$\sim$\`<!-- -->\`{=html}30 s``).

    MyST's tokenizer is stricter and doesn't need the separator, so the
    artifact otherwise survives into the rendered HTML as raw text.
    The pattern is pandoc-specific syntax (raw ``{=html}`` attribute on
    an empty comment) — Markdown authors don't write it by hand, so
    stripping it unconditionally is safe. GH #23.
    """
    return re.sub(r'`<!-- -->`\{=html\}', '', text)


def convert_epigraphs(text: str) -> str:
    """Convert ::: epigraph blocks to blockquotes."""
    text = re.sub(
        r'^::: epigraph\n(.*?)\n^:::',
        lambda m: '\n'.join('> ' + line if line.strip() else '>' for line in m.group(1).split('\n')),
        text,
        flags=re.MULTILINE | re.DOTALL
    )
    return text


def cleanup_typography(text: str) -> str:
    """Clean up remaining TeX artifacts."""
    # Remove standalone % comment lines (LaTeX comments that KaTeX can't handle)
    text = re.sub(r'^\s*%\s*$\n?', '', text, flags=re.MULTILINE)

    # Remove TIKZ placeholder comments (leave a note)
    text = re.sub(
        r'^% TIKZ: (.+?) \(needs manual conversion\)$',
        r'% TODO: TikZ diagram "\1" needs manual conversion',
        text,
        flags=re.MULTILINE
    )

    # Remove \qedhere (LaTeX proof ending marker; sphinx-proof adds its own)
    text = text.replace('\\qedhere', '')

    # Fix pandoc-escaped brackets \[ and \] outside math blocks.
    # MyST interprets \[...\] as display math, so unescape to plain [ and ].
    # Only unescape when \[ is followed by text (not a math expression).
    text = re.sub(r'\\(\[)(?=[A-Z])', r'\1', text)
    text = re.sub(r'(?<=[.!?])\\(\])', r'\1', text)

    # Fix \l| → \lvert and \r| → \rvert (garbled LaTeX delimiters)
    text = re.sub(r'\\l\|', r'\\lvert ', text)
    text = re.sub(r'\\r\|', r'\\rvert ', text)

    # Clean up multiple blank lines (max 2)
    text = re.sub(r'\n{4,}', '\n\n\n', text)

    return text


def compress_directive_whitespace(text: str) -> str:
    """Trim blank lines between adjacent fenced directives.

    A no-op when ``whitespace_compression: readable`` is configured (the
    default). When ``compact`` is selected, runs of blank lines between
    one ``` fence and the next ``` ``` ``{...} `` ` fence are collapsed
    to nothing — adjacent directives sit flush, matching dp1's denser
    source style.

    Deliberately conservative: doesn't touch blank lines after ``:label:``
    (dp1 itself is inconsistent there — sometimes keeps a blank, sometimes
    not — so stripping uniformly would be wrong as often as right) or
    around ``(label)=`` anchors. Compact mode is an approximation, not a
    byte-identical reproduction of dp1's hand-tuned output.

    State coupling: reads ``postprocess._WHITESPACE_STYLE``. Late-import
    of postprocess to avoid circular import at module load (P3a).
    """
    import postprocess
    if postprocess._WHITESPACE_STYLE != 'compact':
        return text

    lines = text.split('\n')
    out: list[str] = []
    i = 0
    n = len(lines)
    while i < n:
        line = lines[i]
        out.append(line)
        # Collapse blank runs between an adjacent pair of fenced directives.
        if line.strip() == '```' and i + 1 < n:
            j = i + 1
            while j < n and lines[j].strip() == '':
                j += 1
            if j > i + 1 and j < n and lines[j].lstrip().startswith('```{'):
                i = j
                continue
        i += 1
    return '\n'.join(out)
