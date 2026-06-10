"""Text-cleanup transforms: pandoc artifact strips, TeX residues,
whitespace compression, epigraph blocks.

None of these touch cross-references or math — they're pure
text-level cleanup that can run independently of the rest of the
pipeline.
"""

from __future__ import annotations

import re

from conversion_context import current_context


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


def convert_pandoc_spans(text: str) -> str:
    """Convert pandoc bracketed spans that mystmd renders literally (#124).

    Pandoc emits ``\\textsc{iid}`` as ``[iid]{.smallcaps}`` and
    ``\\textsf{x}`` as ``[x]{.sans-serif}`` — pandoc-only span syntax that
    mystmd does not implement, so the markup survives onto the page as raw
    text (34 occurrences across 7 dp1 chapters after the #107 ``{\\sc}``
    normalization; any book using native ``\\textsc`` hits the same class).

    - ``[text]{.smallcaps}`` → ``TEXT`` (uppercased — visually equivalent
      for the dominant all-lowercase-acronym use, and the editorial choice
      book-dp1#351 settled on; a true small-caps HTML span can become an
      opt-in config later if a book wants it).
    - ``[text]{.sans-serif}`` → ``text`` (unwrapped — no plain-text
      equivalent, and plain prose beats leaked markup).
    """
    text = re.sub(
        r'\[([^\]\n]+)\]\{\.smallcaps\}',
        lambda m: m.group(1).upper(),
        text,
    )
    text = re.sub(r'\[([^\]\n]+)\]\{\.sans-serif\}', r'\1', text)
    return text


def convert_epigraphs(text: str) -> str:
    """Convert ::: epigraph blocks to blockquotes."""
    text = re.sub(
        r'^::: epigraph\n(.*?)\n^:::',
        lambda m: '\n'.join('> ' + line if line.strip() else '>' for line in m.group(1).split('\n')),
        text,
        flags=re.MULTILINE | re.DOTALL
    )
    return text


# Fence opener: optional indent + run of ≥3 backticks (+ info string).
# Mirrors ``math._FENCE_LINE_RE`` — tilde/colon fences deliberately ignored
# (lesson 040).
_DASH_FENCE_RE = re.compile(r'^[ \t]*(`{3,})(.*)$')

# Directives whose body must stay byte-identical for the dash pass: code
# carriers plus ``{math}`` (KaTeX would treat a Unicode dash as a literal
# char and change the formula).
_DASH_VERBATIM_DIRECTIVES = frozenset({
    'code', 'code-block', 'code-cell', 'eval-rst', 'math',
})

# Within a prose line, spans the dash substitution must never enter:
# inline code, single-line HTML comments (the ``<!--``/``-->`` delimiters
# themselves contain ``--``), dollar math, autolinks / raw HTML tags,
# markdown link targets, and bare URLs.
_DASH_PROTECTED_SPAN_RE = re.compile(
    r'(`+)[^`]*?\1'
    r'|<!--.*?-->'
    r'|\$[^$\n]+\$'
    r'|<[^<> ]*>'
    r'|\]\([^()\s]*\)'
    r'|\S+://\S+'
)

# A run of exactly 2 or 3 hyphens (not part of a longer run). LaTeX
# ligature semantics: ``--`` → en dash, ``---`` → em dash. Runs of 4+
# (ASCII rules, comment art) are left alone.
_DASH_RUN_RE = re.compile(r'(?<!-)(-{2,3})(?!-)')

# Whole lines the pass skips: structural dash lines (YAML frontmatter
# delimiters, thematic breaks, setext underlines, pipe/grid/simple table
# rules) and directive option lines.
_DASH_RULE_LINE_RE = re.compile(r'^[\s|+:=-]+$')
_DASH_OPTION_LINE_RE = re.compile(r'^\s*:[A-Za-z][\w.-]*:')

# Indented code blocks: pandoc writes plain ``verbatim`` environments as
# 4-space-indented code (no fence for the stack to see). A ≥4-space line
# is treated as code UNLESS it opens with a list marker — nested list
# items legitimately sit at that depth. A marker-less list *continuation*
# paragraph is also skipped by this test (a missed prose conversion, the
# cheap failure mode) rather than risking dash-corruption of real code.
_DASH_INDENTED_CODE_RE = re.compile(r'^ {4,}(?![-*+] |\d+[.)] )\S')


def _dash_sub_segment(seg: str) -> str:
    return _DASH_RUN_RE.sub(
        lambda m: '—' if len(m.group(1)) == 3 else '–', seg
    )


def _dash_sub_line(line: str) -> str:
    """Apply the dash substitution outside protected spans of one line."""
    out: list[str] = []
    pos = 0
    for m in _DASH_PROTECTED_SPAN_RE.finditer(line):
        out.append(_dash_sub_segment(line[pos:m.start()]))
        out.append(m.group(0))
        pos = m.end()
    out.append(_dash_sub_segment(line[pos:]))
    return ''.join(out)


def convert_latex_dashes(text: str) -> str:
    """Convert LaTeX dash ligatures surviving in prose to Unicode (#1).

    LaTeX convention: ``--`` is an en dash (``Epstein--Zin``,
    ``(i)--(iii)``), ``---`` an em dash. Pandoc's LaTeX reader converts
    the ligatures correctly, but its markdown writer's default ``smart``
    extension re-encodes the Unicode dashes as ``--``/``---`` — and
    mystmd has no typographer pass, so the hyphens render literally.

    Disabling ``smart`` on the writer (``-t markdown-smart``) is NOT an
    option: the reader also ligatures the ``--`` inside the pipeline's
    ``<!--MARKER-->`` HTML comments, and it is precisely the smart
    writer's re-encoding that restores the marker delimiters. So the
    conversion happens here, post-pandoc, prose-only.

    Line-scan with the lesson-040 fence stack: code fences and
    ``{math}``/code directives pass through verbatim; other directive
    bodies are prose and get the substitution. Per line, structural
    dash lines (frontmatter ``---``, table rules, thematic breaks) and
    directive options are skipped; per segment, inline code, HTML
    comments, ``$…$`` math, autolinks, link targets, and bare URLs are
    protected. Multi-line ``$$`` displays and HTML comments toggle a
    verbatim state. Runs **late** in ``process_text`` (after every
    marker decoder) so decoded prose is visible and no marker comment
    remains to corrupt.
    """
    out: list[str] = []
    stack: list[tuple[int, str]] = []  # (tick_count, 'verbatim'|'prose')
    in_display_math = False
    in_comment = False

    for line in text.split('\n'):
        m = _DASH_FENCE_RE.match(line)
        if m is not None:
            ticks = len(m.group(1))
            rest = m.group(2)
            if stack and rest.strip() == '' and ticks >= stack[-1][0]:
                stack.pop()
                out.append(line)
                continue
            rest_stripped = rest.lstrip()
            if rest_stripped.startswith('{'):
                close = rest_stripped.find('}')
                name = rest_stripped[1:close].strip() if close > 0 else ''
                first_word = name.split()[0] if name else ''
                kind = (
                    'verbatim'
                    if first_word in _DASH_VERBATIM_DIRECTIVES
                    else 'prose'
                )
            else:
                kind = 'verbatim'  # plain code fence
            stack.append((ticks, kind))
            out.append(line)
            continue

        if (stack and stack[-1][1] == 'verbatim') or in_display_math or in_comment:
            out.append(line)
            # State exits checked on the verbatim line itself.
            if in_comment and '-->' in line:
                in_comment = False
            if in_display_math and line.count('$$') % 2 == 1:
                in_display_math = False
            continue

        if _DASH_RULE_LINE_RE.match(line) and '-' in line:
            out.append(line)
            continue
        if _DASH_OPTION_LINE_RE.match(line):
            out.append(line)
            continue
        if _DASH_INDENTED_CODE_RE.match(line):
            out.append(line)
            continue

        # State entries: an unclosed ``$$`` or ``<!--`` puts following
        # lines in verbatim mode until the closer; the tail of THIS line
        # from the opener on is already not prose, so substitute only
        # the prefix. (Same-line closed spans are handled by the
        # per-line protected-span regex.)
        cut = len(line)
        if line.count('$$') % 2 == 1:
            cut = min(cut, line.rfind('$$'))
            in_display_math = True
        if '<!--' in line and '-->' not in line.rsplit('<!--', 1)[1]:
            cut = min(cut, line.rfind('<!--'))
            in_comment = True
        out.append(_dash_sub_line(line[:cut]) + line[cut:])

    return '\n'.join(out)


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


def compress_directive_whitespace(text: str, ctx=None) -> str:
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

    Reads ``ctx.whitespace_style`` (Phase 3); falls back to the current
    context when called without an explicit ``ctx`` (unit-test path).
    """
    ctx = ctx if ctx is not None else current_context()
    if ctx.whitespace_style != 'compact':
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
