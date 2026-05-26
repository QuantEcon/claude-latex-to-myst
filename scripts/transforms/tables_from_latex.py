"""Parse ``\\begin{table}...\\end{table}`` floats directly from LaTeX
source, preserving the header/body structure that pandoc's LaTeX reader
collapses (closes #51, Path C of PR #41).

This module operates on the RAW LATEX SOURCE — before pandoc sees it.
The companion ``scripts/_apply_table_markers.py`` calls into here to
extract structured data from each table block, then replaces the
block with an HTML-comment marker. The post-pandoc resolver
``resolve_table_markers`` (defined below in this module, wired into
``postprocess.py``'s ``process_text``) decodes the markers and emits
MyST ``{table}`` directives.

Why this exists: pandoc's LaTeX reader emits ``simple_tables`` format
for ``\\begin{tabular}{lccc}``-style tables and COLLAPSES all interior
``\\hline``/``\\midrule`` separators. We lose the LaTeX-side header
row identity before pandoc even produces output. By extracting the
block ourselves we keep full structural fidelity.

Scope:
- ``\\begin{table}[pos]?...\\end{table}`` floats only.
- ``\\begin{center}\\begin{tabular}`` (no float wrapper) is handled by
  ``convert_simple_tables`` via pandoc's output — pandoc preserves
  enough structure for that case and rewriting it would be redundant.
- ``\\multicolumn``/``\\multirow`` are NOT handled in this initial
  cut (rare in book content; reachable as a follow-up).

The structural parser is regex-driven, not a full LaTeX parser. It
recognises a bounded subset of common patterns; non-conforming
content falls through unchanged so pandoc still gets a chance.
"""

from __future__ import annotations

import base64
import json
import re
from dataclasses import asdict, dataclass, field


# A row terminator: ``\\`` optionally followed by ``[Xpt]`` length
# spec (``\\[6pt]``) and trailing whitespace. Cell text inside a row
# uses ``&`` as separator.
_ROW_TERMINATOR_RE = re.compile(r'\\\\(?:\[[^\]]*\])?')

# Horizontal rules that delimit table sections:
# - ``\hline``, ``\hline\hline`` (legacy)
# - ``\toprule``, ``\midrule``, ``\bottomrule`` (booktabs)
# - ``\cmidrule{X-Y}`` (booktabs partial rules — treat as a single rule)
# Match either as a standalone token or with trailing whitespace.
_RULE_RE = re.compile(
    r'\\(?:hline|toprule|midrule|bottomrule|cmidrule)(?:\{[^}]*\})?'
)

# A \begin{table}[pos]?...\end{table} block. ``[pos]`` is optional;
# DOTALL so the body can span multiple lines. Non-greedy to allow
# multiple tables in one file.
_TABLE_BLOCK_RE = re.compile(
    r'\\begin\{table\}(?:\[[^\]]*\])?(.*?)\\end\{table\}',
    re.DOTALL,
)

# A \begin{center}...\end{center} block — used for the "center-wrap"
# tabular shape: ``\begin{center}\begin{tabular}{...}...\end{tabular}\end{center}``.
# Pandoc converts ``\begin{center}`` to a ``::: center`` fenced div;
# rather than wrap our emitted MyST table inside that, we substitute
# the whole ``\begin{center}`` block when it contains a tabular.
_CENTER_BLOCK_RE = re.compile(
    r'\\begin\{center\}(.*?)\\end\{center\}',
    re.DOTALL,
)

# Tabular-family environment names. ``tabular`` is the bare form.
# ``tabular*`` takes an extra ``{total-width}`` arg before the colspec.
# ``tabularx`` / ``tabulary`` (package variants) take a ``{width}``
# arg before the colspec.
#
# ``tabu`` is NOT included — the ``tabu`` package's syntax is more
# variable than the others: ``\begin{tabu}{cols}`` (1-arg),
# ``\begin{tabu} to <len> {cols}`` and ``\begin{tabu} spread <len>
# {cols}`` (1-arg with a non-braced ``to``/``spread`` prefix). The
# ``to``/``spread`` keyword can't be skipped with balanced-brace
# extraction. None of the test corpora use ``tabu`` so leaving it
# unrecognised falls back to the pandoc-output path. Add a dedicated
# handler if a future consumer needs it.
_TABULAR_VARIANTS_1ARG = ('tabular',)
_TABULAR_VARIANTS_2ARG = ('tabular*', 'tabularx', 'tabulary')
_TABULAR_ALL = _TABULAR_VARIANTS_1ARG + _TABULAR_VARIANTS_2ARG

# Match the opener of any tabular variant — capture the name so we
# know whether to expect 1 or 2 brace args. The regex group is the
# environment name; escape star for `tabular*` etc.
_TABULAR_OPEN_RE = re.compile(
    r'\\begin\{('
    + '|'.join(re.escape(v) for v in _TABULAR_ALL)
    + r')\}'
)

# Generic end matcher — `\end{X}` for any tabular variant. Includes
# escaped `*` so `\end{tabular*}` matches.
def _tabular_end_re(env_name: str) -> re.Pattern:
    return re.compile(r'\\end\{' + re.escape(env_name) + r'\}')

# Caption + label extraction. Both can appear in any order before or
# after the tabular environment.
_CAPTION_RE = re.compile(r'\\caption\{')
_LABEL_RE = re.compile(r'\\label\{([^}]+)\}')


@dataclass
class TableSpec:
    """Parsed structure of one ``\\begin{table}...\\end{table}`` block.

    Cells contain RAW LATEX at parse time; the caller (typically
    ``_apply_table_markers.py``) converts them to markdown via pandoc
    before storing in the marker.

    ``colspec`` is the column-alignment string from
    ``\\begin{tabular}{...}``, with vertical bars and ``@{}`` columns
    stripped. Used to derive pipe-table alignment (``l``→``:---``,
    ``c``→``:---:``, ``r``→``---:``, ``p{...}``→default left).
    """
    name: str | None
    caption: str | None
    colspec: list[str]
    header_rows: list[list[str]] = field(default_factory=list)
    body_rows: list[list[str]] = field(default_factory=list)


def _find_balanced_brace(s: str, start: int) -> int:
    """Given ``s[start] == '{'``, return the index of the matching
    ``'}'`` (inclusive). Returns -1 if unbalanced.

    Handles escaped braces ``\\{`` / ``\\}`` correctly.
    """
    if start >= len(s) or s[start] != '{':
        return -1
    depth = 0
    i = start
    while i < len(s):
        c = s[i]
        if c == '\\' and i + 1 < len(s):
            i += 2
            continue
        if c == '{':
            depth += 1
        elif c == '}':
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return -1


def _extract_balanced_arg(s: str, command_end: int) -> tuple[str, int]:
    """After matching a command like ``\\caption``, ``s[command_end]``
    should be ``'{'``. Return ``(arg_content, post_close_idx)``."""
    if command_end >= len(s) or s[command_end] != '{':
        return '', command_end
    close = _find_balanced_brace(s, command_end)
    if close == -1:
        return '', command_end
    return s[command_end + 1 : close], close + 1


def _parse_colspec(spec: str) -> list[str]:
    """Parse a tabular column-spec string into a list of per-column
    alignment codes.

    Recognised codes:
    - ``l`` / ``c`` / ``r``: left / center / right
    - ``p{...}`` / ``m{...}`` / ``b{...}``: fixed-width → ``l`` (mystmd
      pipe-table defaults to left for non-aligned columns)
    - ``X``: tabularx flex → ``l``
    Ignored:
    - ``|``: vertical rule
    - ``@{...}`` / ``!{...}``: column separators with content
    - ``>{...}`` / ``<{...}``: cell-content modifiers (prefix/suffix)
    - ``*{N}{spec}``: repeat — expanded inline

    Unknown characters are skipped.
    """
    cols: list[str] = []
    i = 0
    while i < len(spec):
        c = spec[i]
        if c in 'lcr':
            cols.append(c)
            i += 1
        elif c in 'pmb':
            # Skip the {...} width arg.
            j = i + 1
            if j < len(spec) and spec[j] == '{':
                close = _find_balanced_brace(spec, j)
                i = close + 1 if close != -1 else j + 1
            else:
                i += 1
            cols.append('l')
        elif c == 'X':
            cols.append('l')
            i += 1
        elif c == '*':
            # \*{N}{spec} — repeat. Best-effort parse.
            j = i + 1
            if j < len(spec) and spec[j] == '{':
                n_close = _find_balanced_brace(spec, j)
                if n_close == -1:
                    i += 1
                    continue
                n_str = spec[j + 1 : n_close]
                k = n_close + 1
                if k < len(spec) and spec[k] == '{':
                    inner_close = _find_balanced_brace(spec, k)
                    if inner_close == -1:
                        i = k
                        continue
                    inner_spec = spec[k + 1 : inner_close]
                    try:
                        n = int(n_str.strip())
                    except ValueError:
                        n = 1
                    cols.extend(_parse_colspec(inner_spec) * n)
                    i = inner_close + 1
                else:
                    i = k
            else:
                i += 1
        elif c in '|@!><':
            # Vertical rule (``|``) or separator/modifier with arg
            # (``@{}``, ``!{}``, ``>{...}``, ``<{...}``). Modifiers
            # carry a braced argument that must be skipped — anything
            # inside (``\bfseries``, ``\centering``, ``$``) can contain
            # ``l``/``c``/``r`` chars that would otherwise be
            # misparsed as real columns. ``|`` has no arg.
            if c in '@!><':
                j = i + 1
                if j < len(spec) and spec[j] == '{':
                    close = _find_balanced_brace(spec, j)
                    i = close + 1 if close != -1 else j + 1
                    continue
            i += 1
        else:
            i += 1
    return cols


def _strip_block_commands(body: str) -> str:
    """Drop tabular-internal commands that don't affect cell content:
    ``\\centering``, ``\\setlength{}{}``, ``\\renewcommand{}{}``,
    ``\\arraystretch``, etc.

    Cell-content commands (``\\textbf{}``, ``\\cref{}``, etc.) are
    preserved — they'll be converted to markdown by pandoc later.
    """
    # \setlength{X}{Y} — two balanced-brace args.
    for cmd in (r'\\setlength', r'\\renewcommand', r'\\arrayrulewidth'):
        body = re.sub(cmd + r'\s*\{[^}]*\}\s*\{[^}]*\}', '', body)
    # \centering, \arraystretch, \tabcolsep — single bare command.
    for cmd in (r'\\centering', r'\\small', r'\\footnotesize',
                r'\\normalsize'):
        body = re.sub(cmd + r'\b', '', body)
    return body


def _split_row_cells(row: str) -> list[str]:
    """Split a row's LaTeX into cells on ``&``, respecting balanced
    braces (so ``\\textbf{a & b}`` stays as one cell)."""
    cells: list[str] = []
    depth = 0
    cur = []
    i = 0
    while i < len(row):
        c = row[i]
        if c == '\\' and i + 1 < len(row):
            cur.append(row[i])
            cur.append(row[i + 1])
            i += 2
            continue
        if c == '{':
            depth += 1
            cur.append(c)
        elif c == '}':
            depth -= 1
            cur.append(c)
        elif c == '&' and depth == 0:
            cells.append(''.join(cur).strip())
            cur = []
        else:
            cur.append(c)
        i += 1
    cells.append(''.join(cur).strip())
    return cells


def _split_rows_by_rules(body: str) -> list[tuple[str, list[list[str]]]]:
    """Slice the tabular body into rule-bounded sections.

    Returns ``[(section_kind, rows), ...]`` where ``section_kind`` is
    one of ``'top'`` (above the first rule), ``'middle'`` (between
    interior rules), or ``'bottom'`` (below the last rule). ``rows``
    is a list of rows; each row is a list of cells.

    The header/body split is determined later by the caller — first
    non-empty section becomes header (if there are 2+ sections), the
    rest become body.
    """
    body = _strip_block_commands(body)

    # Find all rule positions.
    rule_positions: list[tuple[int, int]] = []
    for m in _RULE_RE.finditer(body):
        rule_positions.append((m.start(), m.end()))

    # Section boundaries: 0 → rule1_start, rule1_end → rule2_start, ...
    sections: list[str] = []
    last_end = 0
    for r_start, r_end in rule_positions:
        sections.append(body[last_end:r_start])
        last_end = r_end
    sections.append(body[last_end:])

    # Parse rows in each section.
    parsed: list[tuple[str, list[list[str]]]] = []
    for sec_idx, sec_text in enumerate(sections):
        # Section name (just for debugging).
        if sec_idx == 0:
            kind = 'top'
        elif sec_idx == len(sections) - 1:
            kind = 'bottom'
        else:
            kind = 'middle'

        rows = _split_into_rows(sec_text)
        parsed.append((kind, rows))
    return parsed


def _split_into_rows(text: str) -> list[list[str]]:
    """Split text on ``\\\\`` row terminators, then split each row's
    cells on ``&``. Skip empty / whitespace-only rows."""
    if not text.strip():
        return []
    # Split on \\ row terminator (with optional [length] arg).
    pieces = _ROW_TERMINATOR_RE.split(text)
    rows: list[list[str]] = []
    for piece in pieces:
        if not piece.strip():
            continue
        cells = _split_row_cells(piece)
        # Drop rows that are all-empty (whitespace).
        if any(c.strip() for c in cells):
            rows.append(cells)
    return rows


def parse_table_block(block_body: str) -> TableSpec | None:
    """Parse a ``\\begin{table}...\\end{table}`` block's interior.

    ``block_body`` is the content BETWEEN ``\\begin{table}[pos]?`` and
    ``\\end{table}`` (i.e., what's captured by ``_TABLE_BLOCK_RE``
    group 1). Returns ``None`` if no ``\\begin{tabular}`` is found.

    Caption and label are scanned in the WHOLE block (they can sit
    before or after the tabular environment). Rule semantics:

    - Sections above the first rule and below the last rule are
      treated as bounding rules (top/bottom) — their rows are
      typically empty.
    - The boundary between header and body is the FIRST interior rule
      that has non-empty content above it. Empty sections (just
      whitespace) are skipped.
    """
    # Find the tabular-variant environment opener.
    open_m = _TABULAR_OPEN_RE.search(block_body)
    if not open_m:
        return None
    env_name = open_m.group(1)
    # ``tabular*`` / ``tabularx`` / ``tabulary`` / ``tabu`` take an
    # extra ``{width}`` arg BEFORE the colspec; skip it via
    # balanced-brace extraction. ``tabular`` (the bare form) takes
    # only the colspec.
    cursor = open_m.end()
    # Walk past any whitespace.
    while cursor < len(block_body) and block_body[cursor] in ' \t\n':
        cursor += 1
    if env_name in _TABULAR_VARIANTS_2ARG:
        # First arg = width spec, balance-brace-extract and discard.
        if cursor >= len(block_body) or block_body[cursor] != '{':
            return None
        width_close = _find_balanced_brace(block_body, cursor)
        if width_close == -1:
            return None
        cursor = width_close + 1
        while cursor < len(block_body) and block_body[cursor] in ' \t\n':
            cursor += 1
    # Colspec arg.
    if cursor >= len(block_body) or block_body[cursor] != '{':
        return None
    spec_open = cursor
    spec_close = _find_balanced_brace(block_body, spec_open)
    if spec_close == -1:
        return None
    colspec_str = block_body[spec_open + 1 : spec_close]
    # The tabular body runs from after the spec to ``\end{<env>}``.
    end_m = _tabular_end_re(env_name).search(block_body, spec_close + 1)
    if not end_m:
        return None
    tab_body = block_body[spec_close + 1 : end_m.start()]

    # Extract caption (balanced-brace) and label from the WHOLE block.
    # ``_CAPTION_RE`` matches ``\caption{`` — ``cap_m.end() - 1`` is
    # the index of the opening brace, which is what
    # ``_extract_balanced_arg`` expects.
    caption: str | None = None
    cap_m = _CAPTION_RE.search(block_body)
    if cap_m:
        arg, _ = _extract_balanced_arg(block_body, cap_m.end() - 1)
        caption = arg.strip() if arg else None
        # If the label sits inside the caption, also find it there.
        if caption and r'\label{' in caption:
            # Strip \label{...} from caption text.
            caption = re.sub(r'\\label\{[^}]+\}\s*', '', caption).strip()

    # If no explicit ``\caption{}`` was found, look for a "bold-title
    # paragraph" pattern immediately before the tabular: ``\textbf{X}
    # \par\smallskip?`` optionally followed by font-size /
    # arraystretch / centering commands. This is the de-facto title
    # convention for ``\begin{center}\textbf{X}\par\begin{tabular}``
    # shapes (e.g. Deep-Learning's ``execution_map``). Without this
    # promotion the title is silently dropped — caught by PR #60
    # retest. Skip when an explicit caption already exists so we
    # don't clobber it.
    if caption is None:
        # Look at the region BETWEEN the start of block_body and the
        # tabular opener for the title pattern. ``\textbf{TEXT}\par``
        # (with optional trailing skip + intervening config commands)
        # must be the LAST non-whitespace content before the tabular.
        prelude = block_body[: open_m.start()]
        title_m = re.search(
            r'\\textbf\{([^{}]+)\}\s*\\par'              # \textbf{X}\par
            r'(?:\s*\\(?:small|med|big)skip)?'           # optional \smallskip etc.
            r'\s*(?:\\(?:scriptsize|small|footnotesize|normalsize)\s*)*'  # font cmds
            r'\s*(?:\\renewcommand\{[^}]*\}\{[^}]*\}\s*)*'  # arraystretch etc.
            r'\s*\Z',  # ...immediately before the tabular opener
            prelude,
        )
        if title_m:
            caption = title_m.group(1).strip()

    name: str | None = None
    label_m = _LABEL_RE.search(block_body)
    if label_m:
        # convert tab:foo → tab-foo for MyST.
        raw = label_m.group(1)
        name = raw.replace(':', '-')

    colspec = _parse_colspec(colspec_str)

    sections = _split_rows_by_rules(tab_body)

    # Filter out empty sections.
    non_empty = [(k, rows) for k, rows in sections if rows]

    spec = TableSpec(name=name, caption=caption, colspec=colspec)

    if not non_empty:
        return spec  # empty table (rare)

    if len(non_empty) == 1:
        # No interior rule separating sections — single block, no header.
        spec.body_rows = non_empty[0][1]
    else:
        # Multiple non-empty sections: first is header, rest are body.
        # (LaTeX-side `\hline` after the header row in book content is
        # the canonical header/body separator. Any further interior
        # `\hline`s are visual grouping within the body.)
        spec.header_rows = non_empty[0][1]
        for _, rows in non_empty[1:]:
            spec.body_rows.extend(rows)

    return spec


# Environments whose contents should NEVER be extracted as tabulars
# even if they contain ``\begin{tabular}``-shaped content. Math envs
# (matrix-like layouts), Beamer slide envs (which our pipeline doesn't
# build but tex sources may contain), TikZ diagrams (tabular-in-node
# matrix layouts), figure-family envs (where a tabular is figure
# content, not a standalone table), and custom envs whose semantics
# we can't infer.
_SKIP_ANCESTOR_ENVS = frozenset({
    # Math
    'equation', 'equation*', 'align', 'align*', 'gather', 'gather*',
    'multline', 'multline*', 'eqnarray', 'eqnarray*', 'array',
    'matrix', 'pmatrix', 'bmatrix', 'vmatrix', 'Vmatrix', 'smallmatrix',
    'cases', 'displaymath', 'math', 'split',
    # Beamer slide envs (our pipeline doesn't build these but source
    # files may contain a ``mystmd``-input mode that mixes slide +
    # manuscript content)
    'frame', 'columns', 'column', 'block', 'alertblock', 'exampleblock',
    # Diagrams
    'tikzpicture', 'tikzcd',
    # Figure-family — a tabular inside a figure is figure content
    # (caption attaches to the figure, not the table). Skipping
    # leaves it for ``convert_figures`` / ``convert_simple_tables``
    # to handle via the pandoc-output path.
    'figure', 'subfigure', 'minipage', 'wrapfigure', 'sidewaystable',
    # Comment env (``\begin{comment}...\end{comment}`` from the
    # ``comment`` package — content is suppressed in PDF; pandoc
    # passes through)
    'comment',
    # Custom-content envs commonly used in books
    'definitionbox', 'theorembox', 'proofbox',
})


def _ancestor_stack(text: str, pos: int) -> list[str]:
    """Return the stack of unclosed ``\\begin{X}`` environments at
    ``pos`` in ``text``, outermost first. Empty list if at top level.

    Walks all ``\\begin{X}`` / ``\\end{X}`` events before ``pos`` in
    source order. Comment-line occurrences are filtered out.

    Returns the FULL stack (not just nearest) because skip-ancestor
    decisions need to consider deep wrappers: a tabular inside
    ``\\begin{frame}\\begin{center}\\begin{tabular}`` has ``center``
    as its nearest ancestor (not in skip set) but ``frame`` deeper
    in the stack (in skip set). Checking only the nearest would
    incorrectly extract.
    """
    pattern = re.compile(r'\\(begin|end)\{(\w+\*?)\}')
    stack: list[str] = []
    for m in pattern.finditer(text, 0, pos):
        if _starts_in_comment(text, m.start()):
            continue
        kind = m.group(1)
        name = m.group(2)
        if kind == 'begin':
            stack.append(name)
        else:  # end
            if stack and stack[-1] == name:
                stack.pop()
            # If unmatched end, just ignore — defensive.
    return stack


def _has_skip_ancestor(text: str, pos: int) -> bool:
    """True if ANY ancestor in the env stack at ``pos`` is in
    ``_SKIP_ANCESTOR_ENVS``. Used to skip tabulars whose surrounding
    context is unsafe to extract (math, slides, tikz, figure-family)."""
    return any(env in _SKIP_ANCESTOR_ENVS for env in _ancestor_stack(text, pos))


def _nearest_unclosed_env(text: str, pos: int) -> str | None:
    """Return the name of the nearest unclosed ``\\begin{X}`` ancestor
    at ``pos``, or ``None`` if at top level. Convenience wrapper
    around ``_ancestor_stack``. Useful for classifying tabular
    context (``table`` → captioned float, ``center`` → center-wrap,
    ``None`` → bare)."""
    stack = _ancestor_stack(text, pos)
    return stack[-1] if stack else None


def find_table_blocks(text: str) -> list[tuple[int, int, str]]:
    """Find all tabular-bearing blocks in ``text`` that should be
    extracted via the marker preprocessor.

    Three discovery shapes (in priority order):

    1. **Table float**: ``\\begin{table}[pos]?...\\end{table}``. The
       block body is the content inside, which carries the caption
       and label.

    2. **Center wrap**: ``\\begin{center}...\\end{center}`` where the
       inside contains a tabular variant (``\\begin{tabular}``,
       ``\\begin{tabularx}``, etc.). The whole ``\\begin{center}``
       block is substituted so pandoc doesn't wrap the emitted MyST
       table in a ``::: center`` fenced div. No caption/label
       (center-wrapped tables are not enumerable LaTeX floats).

    3. **Bare**: ``\\begin{tabular}...\\end{tabular}`` (or any
       tabular variant) NOT inside the above. Substituted directly.
       No caption/label.

    Tabulars inside math envs, Beamer slide envs, or TikZ pictures
    are skipped via ``_nearest_unclosed_env`` (see
    ``_SKIP_ANCESTOR_ENVS``). Comment-line blocks are skipped.

    Returns ``(start_idx, end_idx, body)`` tuples in source order.
    ``body`` is the content fed to ``parse_table_block`` for each
    shape — for shapes 1 and 2 it's the WHOLE wrapper's inside; for
    shape 3 it's the tabular itself including ``\\begin``/``\\end``.
    """
    blocks: list[tuple[int, int, str]] = []
    consumed_ranges: list[tuple[int, int]] = []  # ranges already claimed

    def _claimed(pos: int) -> bool:
        return any(s <= pos < e for s, e in consumed_ranges)

    # 1. Table floats (existing behaviour). Also subject to the
    # whole-ancestor-stack skip check so e.g.
    # ``\begin{frame}\begin{table}...\end{table}\end{frame}`` (a
    # captioned table inside a Beamer slide) is left for pandoc to
    # handle — extracting would inject a ``{table}`` directive
    # inside slide content the pipeline doesn't build anyway.
    for m in _TABLE_BLOCK_RE.finditer(text):
        if _starts_in_comment(text, m.start()):
            continue
        if _has_skip_ancestor(text, m.start()):
            continue
        blocks.append((m.start(), m.end(), m.group(1)))
        consumed_ranges.append((m.start(), m.end()))

    # 2. Center-wraps containing a tabular variant.
    for m in _CENTER_BLOCK_RE.finditer(text):
        if _starts_in_comment(text, m.start()):
            continue
        if _claimed(m.start()):
            continue
        inner = m.group(1)
        # Only claim if the center-block actually contains a tabular.
        if not _TABULAR_OPEN_RE.search(inner):
            continue
        # Skip if ANY ancestor (not just nearest) is in the skip set
        # — e.g. ``\begin{frame}\begin{center}\begin{tabular}`` has
        # ``center`` as nearest (process candidate) but ``frame``
        # deeper (skip). We don't extract from inside Beamer slides.
        if _has_skip_ancestor(text, m.start()):
            continue
        blocks.append((m.start(), m.end(), m.group(1)))
        consumed_ranges.append((m.start(), m.end()))

    # 3. Bare tabular variants — anything left that we haven't claimed.
    for m in _TABULAR_OPEN_RE.finditer(text):
        if _starts_in_comment(text, m.start()):
            continue
        if _claimed(m.start()):
            continue
        # Skip if any ancestor is in the skip set. This catches both
        # the nearest (``\begin{tikzpicture}\begin{tabular}``) and
        # deep wrappers (``\begin{frame}\begin{tabular}``).
        if _has_skip_ancestor(text, m.start()):
            continue
        # Find the matching \end{<env>} for the tabular variant.
        env_name = m.group(1)
        end_m = _tabular_end_re(env_name).search(text, m.end())
        if end_m is None:
            continue
        # Body for bare tabular is the WHOLE tabular block (including
        # \begin/\end markers) — parse_table_block looks for
        # \begin{tabular} inside.
        start = m.start()
        end = end_m.end()
        if _claimed(start):
            continue
        blocks.append((start, end, text[start:end]))
        consumed_ranges.append((start, end))

    # Sort by source position so substitution preserves order.
    blocks.sort(key=lambda b: b[0])
    return blocks


def _starts_in_comment(text: str, pos: int) -> bool:
    """Return True if ``text[pos]`` sits in a LaTeX line-comment —
    same physical line has an unescaped ``%`` before ``pos``.

    Same logic as ``_apply_listing_markers.py::_starts_in_comment``."""
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


# Marker format. The marker is an HTML comment that pandoc passes
# through verbatim (no markdown parsing inside). The payload is
# base64-encoded JSON to survive pandoc whitespace / escape behaviour
# unchanged. Decoded payload structure:
#
#   {
#     "name": "tab-foo" | null,
#     "caption": "...converted markdown..." | null,
#     "colspec": ["l", "c", "c", "c"],
#     "header_rows": [["cell1-md", "cell2-md", ...], ...],
#     "body_rows": [["cell1-md", ...], ...],
#   }
#
# ``caption`` and cells are MARKDOWN at marker-write time (not raw
# LaTeX) — the preprocessor batches them through pandoc once per
# file before writing. This lets ``resolve_table_markers`` emit MyST
# without spawning pandoc itself, and lets downstream transforms
# (make_ref, citations, math) process the cell content the same way
# they process pandoc's other output.
_MARKER_OPEN = '<!--TABLE '
_MARKER_CLOSE = '-->'

_MARKER_RE = re.compile(
    r'\\?<!--TABLE\s+payload=(?P<payload>[A-Za-z0-9+/=]+)--\\?>',
)


def encode_marker(spec: TableSpec) -> str:
    """Encode a ``TableSpec`` as a one-line HTML-comment marker.

    Cells should already be markdown-converted before this is called
    (see ``_apply_table_markers.py``). The marker is a single line so
    pandoc treats it as a self-contained block; multi-line markers
    risk paragraph splitting on certain pandoc versions.
    """
    payload = base64.b64encode(
        json.dumps(asdict(spec), ensure_ascii=False).encode('utf-8')
    ).decode('ascii')
    return f'{_MARKER_OPEN}payload={payload}{_MARKER_CLOSE}'


def decode_marker(payload_b64: str) -> TableSpec:
    """Decode a marker payload back to a ``TableSpec``.

    Raises on malformed payloads (invalid base64, non-JSON content, JSON
    that lacks the structural fields). Callers (``resolve_table_markers``)
    handle the exception by leaving the original marker in place — see
    the defensive ``try/except`` there. ``name`` and ``caption`` use
    ``.get`` because they're legitimately optional; ``colspec``,
    ``header_rows``, and ``body_rows`` are structural and indexed
    directly so missing keys raise ``KeyError``.
    """
    raw = base64.b64decode(payload_b64.encode('ascii')).decode('utf-8')
    data = json.loads(raw)
    return TableSpec(
        name=data.get('name'),
        caption=data.get('caption'),
        colspec=data['colspec'],
        header_rows=data['header_rows'],
        body_rows=data['body_rows'],
    )


def _escape_pipe_cell(cell: str) -> str:
    """Escape ``|`` to ``\\|`` so pipe-table cells survive parsing
    when content contains literal pipes (rare in practice: ``|x|``
    absolute value in math, code with pipes, etc.)."""
    return cell.replace('|', r'\|')


def emit_myst(spec: TableSpec) -> str:
    """Emit MyST directive lines for the parsed table.

    Output shape:

    - With caption: ``{table}`` directive wrapping the body.
      Pipe-table body when exactly 1 header row (the common case);
      ``{list-table}`` fallback for 0 or 2+ header rows.
    - Without caption: bare pipe-table (mystmd renders it as a
      non-enumerable table — the caller decides whether to add a
      label via the surrounding context).

    Cells are emitted verbatim (already markdown at this point);
    only ``|`` characters are escaped for pipe-table compatibility.
    """
    has_header = len(spec.header_rows) == 1
    all_rows = spec.header_rows + spec.body_rows
    if not all_rows:
        return ''

    ncols = max(len(r) for r in all_rows)
    if ncols == 0:
        return ''

    def fmt_row(row: list[str]) -> str:
        padded = row + [''] * (ncols - len(row))
        return '| ' + ' | '.join(_escape_pipe_cell(c) for c in padded) + ' |'

    def fmt_align() -> str:
        # Pipe-table alignment markers from colspec.
        cells: list[str] = []
        for k in range(ncols):
            if k < len(spec.colspec):
                a = spec.colspec[k]
            else:
                a = 'l'
            if a == 'c':
                cells.append(':---:')
            elif a == 'r':
                cells.append('---:')
            else:  # l or default
                cells.append('---')
        return '|' + '|'.join(cells) + '|'

    # A ``{table}`` wrapper is needed whenever the table carries a
    # caption OR a name (label) — both attach to the enumerable
    # container, not to the pipe-table body. Tables with neither are
    # rare in ``\begin{table}`` floats (an author who wraps in
    # ``\begin{table}`` almost always also adds ``\caption`` or
    # ``\label``) but the path is supported for completeness.
    needs_wrapper = spec.caption is not None or spec.name is not None

    def emit_body() -> list[str]:
        """Inner body — pipe-table for the 1-header common case,
        ``{list-table}`` fallback for 0 / 2+ header rows."""
        body: list[str] = []
        if has_header:
            body.append(fmt_row(spec.header_rows[0]))
            body.append(fmt_align())
            for row in spec.body_rows:
                body.append(fmt_row(row))
        else:
            # Pipe-tables only support a single header row; mystmd
            # renders 0-header pipe-tables with a visible synthetic
            # empty row, so the {list-table} fallback is cleaner.
            body.append('```{list-table}')
            body.append(f':header-rows: {len(spec.header_rows)}')
            body.append('')
            for row in all_rows:
                body.append(f'* - {row[0] if row else ""}')
                for cell in row[1:]:
                    body.append(f'  - {cell}')
            body.append('```')
        return body

    out: list[str] = []
    if needs_wrapper:
        out.append('````{table}')
        if spec.name:
            out.append(f':name: {spec.name}')
        out.append('')
        if spec.caption:
            out.append(spec.caption)
            out.append('')
        out.extend(emit_body())
        out.append('````')
    else:
        out.extend(emit_body())

    return '\n'.join(out)


def resolve_table_markers(text: str) -> str:
    """Decode ``<!--TABLE payload=BASE64-->`` markers in pandoc's
    markdown output, emit MyST table directives in their place.

    Marker survives pandoc as ``\\<!--TABLE payload=...--\\>`` (pandoc
    escapes the angle brackets). The regex tolerates both escaped and
    unescaped forms.

    This is the post-pandoc counterpart to
    ``scripts/_apply_table_markers.py`` — the round-trip that closes
    #51 by bypassing pandoc's lossy LaTeX-tabular reader entirely.
    """
    def repl(m: re.Match) -> str:
        # Defensive: a corrupted payload (manual edit of the
        # intermediate file, partial copy-paste, future pandoc version
        # that mangles the marker) shouldn't crash the whole
        # postprocess pipeline. Leave the original marker in place on
        # failure — the visible artefact tells the author something
        # went wrong without taking down the build. Mirrors the
        # defensive decode in ``resolve_algorithms``.
        try:
            spec = decode_marker(m.group('payload'))
            return emit_myst(spec)
        except Exception:
            return m.group(0)

    return _MARKER_RE.sub(repl, text)
