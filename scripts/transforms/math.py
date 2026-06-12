"""Math-related transforms.

Converts pandoc's display-math blocks into MyST-compatible shapes,
extracts ``\\label{}`` from anywhere in math bodies (lessons 024 /
032 / 037), repairs ``\\text{...$...$...}`` for KaTeX, and handles
whitespace around inline / display math.

The label-extraction helper ``_extract_math_labels`` services
``align`` / ``multline`` / ``gather`` uniformly.
"""

from __future__ import annotations

import re

from ._helpers import convert_label_colons


def fix_text_dollar(text: str) -> str:
    r"""Fix \text{...$...$...} for KaTeX compatibility.

    KaTeX cannot handle $ inside \text{}. Transform:
      \text{before $math$ after} → \text{before } math \text{ after}
    """
    output = []
    i = 0
    while i < len(text):
        # Look for \text{
        m = re.search(r'\\text\s*\{', text[i:])
        if not m:
            output.append(text[i:])
            break

        # Append everything before \text{
        output.append(text[i:i + m.start()])
        brace_start = i + m.end()

        # Find matching } with brace counting
        depth = 1
        j = brace_start
        while j < len(text) and depth > 0:
            if text[j] == '{' and (j == 0 or text[j-1] != '\\'):
                depth += 1
            elif text[j] == '}' and (j == 0 or text[j-1] != '\\'):
                depth -= 1
            j += 1

        content = text[brace_start:j-1]  # content inside \text{...}

        if '$' not in content:
            # No dollar signs — emit as-is
            output.append(text[i + m.start():j])
            i = j
            continue

        # Split content on $...$ pairs
        parts = re.split(r'\$([^$]*)\$', content)
        # parts[0], parts[2], parts[4], ... are text segments
        # parts[1], parts[3], parts[5], ... are math segments

        segments = []
        for k, part in enumerate(parts):
            if k % 2 == 0:
                # Text segment
                if part:
                    segments.append(r'\text{' + part + '}')
            else:
                # Math segment
                segments.append(part)

        output.append(' '.join(s for s in segments if s))
        i = j

    return ''.join(output)


# Directives whose body is literal source code (must be preserved
# verbatim across the rewrite). Everything else with a ``\`\`\`{name}``
# opener is treated as a *content* directive — its body is markdown /
# math the rewrite must reach.
_CODE_DIRECTIVE_NAMES = frozenset({
    'code-block', 'code-cell', 'code', 'eval-rst',
})

_FENCE_LINE_RE = re.compile(r'^(`{3,})(.*)$')
_INLINE_CODE_RE = re.compile(r'(`[^`\n]+`)')
_REWRITE_PAT = re.compile(r'\\,\^')
_REWRITE_REPL = r'\\,{}^'


def _rewrite_outside_inline_code(line: str) -> str:
    """Apply ``\\,^`` → ``\\,{}^`` to ``line``, preserving any inline
    code spans (``\\`…\\```) inside it so a literal example in prose
    isn't mangled."""
    parts = _INLINE_CODE_RE.split(line)
    # _INLINE_CODE_RE has one capture group → split returns alternating
    # non-match / match segments. Match segments (odd indices) are
    # inline-code spans and stay verbatim.
    for i in range(0, len(parts), 2):
        parts[i] = _REWRITE_PAT.sub(_REWRITE_REPL, parts[i])
    return ''.join(parts)


def fix_spacing_superscript(text: str) -> str:
    r"""Give a superscript that directly follows a thin space an explicit
    empty base, for KaTeX compatibility (closes #45, #85, #87).

    ``\,^\circ`` — e.g. ``3\,^\circ\mathrm{C}`` for degrees Celsius — is
    valid LaTeX: the superscript attaches to an implicit empty base. But
    KaTeX errors with ``Got group of unknown type: 'internal'`` because
    it tries to superscript the ``\,`` spacing node itself. The break
    affects ANY superscript right after ``\,`` (``\,^*``, ``\,^\dagger``,
    ``\,^\top`` …), not just ``^\circ`` — so the rewrite is generic.

    Inserting an explicit empty group — ``\,{}^`` — gives the superscript
    a real (empty) base; KaTeX renders it and the output is visually
    identical. Idempotent: ``\,{}^`` no longer contains ``\,^``.

    NB: the workaround suggested in #45, ``\,\!^``, does NOT work — it
    was verified still-erroring against KaTeX (myst 1.9.1). Only the
    empty-base group fixes it.

    Runs **late** in ``process_text``, after every marker decoder
    (``resolve_table_markers``, ``resolve_exercise_markers``,
    ``resolve_listings``, ``resolve_algorithms``,
    ``resolve_algorithmics``). Those preprocessors base64-encode their
    body content into HTML-comment markers pre-pandoc, so the math
    inside is invisible to any text-level regex until the decoder runs
    — an earlier-position call would miss table cells, algorithm
    bodies, etc.

    Implementation: a line-based scan with a fence stack. Each fenced
    block is classified by its opener:

    - **code-bearing** — bare ``\`\`\`…``, ``\`\`\`python``, or a
      directive in ``_CODE_DIRECTIVE_NAMES`` (``{code-block}``,
      ``{code-cell}``, ``{code}``, ``{eval-rst}``). Body is emitted
      verbatim.
    - **content** — any other ``\`\`\`{name}`` directive
      (``{table}``, ``{figure}``, ``{exercise}``, ``{prf:*}``, …).
      Body lines are passed through ``_rewrite_outside_inline_code``,
      so math inside is fixed but inline ``\``` example spans survive.

    Closers are identified by the stack (a bare ``\`\`\`…`` of ≥ the
    top's tick count), not by another regex match — so a content
    directive's closing ``\`\`\`` cannot be mis-paired with a later
    bare fence (issue #87). Inline-code spans within a line are
    protected per-line; there is no stash/restore step at all, which
    eliminates the marker-leak content-loss class entirely (also #87).
    """
    out: list[str] = []
    # Stack of (tick_count, kind) where kind ∈ {'code', 'content'}.
    stack: list[tuple[int, str]] = []

    for line in text.split('\n'):
        m = _FENCE_LINE_RE.match(line)
        if m is not None:
            ticks = len(m.group(1))
            rest = m.group(2)

            # Closer for the top of stack? A bare ``\`\`\`…`` (optionally
            # trailing whitespace, no info string) of ≥ the opener's tick
            # count closes the fence.
            if stack and rest.strip() == '' and ticks >= stack[-1][0]:
                stack.pop()
                out.append(line)
                continue

            # Otherwise this is a new opener (possibly nested).
            rest_stripped = rest.lstrip()
            if rest_stripped.startswith('{'):
                close = rest_stripped.find('}')
                name = rest_stripped[1:close].strip() if close > 0 else ''
                first_word = name.split()[0] if name else ''
                kind = 'code' if first_word in _CODE_DIRECTIVE_NAMES else 'content'
            else:
                # No ``{name}`` after the backticks → plain code fence.
                kind = 'code'
            stack.append((ticks, kind))
            # Opener line itself: content openers may carry a caption arg
            # / option-line math, so rewrite. Code openers stay verbatim
            # (preserves the language tag and any ``:name:`` etc.).
            if kind == 'content':
                out.append(_rewrite_outside_inline_code(line))
            else:
                out.append(line)
            continue

        # Non-fence line.
        if not stack or stack[-1][1] == 'content':
            out.append(_rewrite_outside_inline_code(line))
        else:
            out.append(line)

    return '\n'.join(out)


def _blockify_math_directives(text: str) -> str:
    """Ensure the ``{math}`` directives emitted for starred envs (#113) sit on
    their own block. A directive is block-level — it cannot share a line with
    prose — but pandoc's ``--wrap=none`` can abut the opening fence to
    preceding prose (the inline-close/display-open ``$\\Xsf$ $$`` case) or
    leave trailing prose after the closing fence. Split both so MyST parses
    the directive. Only ``` ```{math} ``` blocks are touched (the only fenced
    directive ``convert_equations`` emits)."""
    if '```{math}' not in text:
        return text
    out: list[str] = []
    in_math = False
    lines = text.split('\n')
    i = 0
    while i < len(lines):
        line = lines[i]
        if not in_math:
            idx = line.find('```{math}')
            if idx != -1:
                before = line[:idx].rstrip()
                if before:
                    out.append(before)
                    out.append('')
                out.append(line[idx:])
                in_math = True
            else:
                out.append(line)
        else:
            stripped = line.lstrip()
            if stripped.startswith('```'):
                # Closing fence; capture any trailing prose on the same line.
                fence_end = len(line) - len(stripped) + 3
                tail = line[fence_end:].lstrip()
                out.append(line[:fence_end])
                in_math = False
                if tail:
                    out.append('')
                    # The tail may itself contain the NEXT directive's opening
                    # fence — pandoc's --wrap=none plus LaTeX %-gluing can put
                    # "``` prose ```{math}" on one source line (two starred
                    # displays with prose between, found in the dp1 parity
                    # run). Re-scan it instead of appending blindly, else that
                    # opener leaks mid-line as broken MyST.
                    lines[i] = tail
                    continue
            else:
                out.append(line)
        i += 1
    return '\n'.join(out)


def _emit_unnumbered_math(content: str, label: str | None = None) -> str:
    """Emit an explicitly *unnumbered* display-math block (issue #113).

    A starred LaTeX env (``equation*`` / ``align*`` / ``gather*`` /
    ``multline*``) is unnumbered, but a bare ``$$…$$`` is still assigned a
    number by mystmd under book-wide numbering (``numbering: book: true``).
    Confirmed against myst v1.9.1: a label-less ``$$`` gets an ``enumerator``,
    while a ``{math}`` directive with ``:enumerated: false`` does not (and
    doesn't advance the counter). So starred envs round-trip as a ``{math}``
    directive forced unnumbered — preserving LaTeX's numbering exactly."""
    lines = ['```{math}']
    if label:
        lines.append(f':label: {label}')
    lines.append(':enumerated: false')
    lines.append('')
    lines.append(content)
    lines.append('```')
    return '\n'.join(lines)


def convert_equations(text: str) -> str:
    """Convert pandoc equation blocks to MyST format.

    Patterns:
    - $$\\begin{equation}\\label{eq:foo} ... \\end{equation}$$
      → $$ ... $$ (eq-foo)
    - $$\\begin{equation*} ... \\end{equation*}$$
      → ```{math} :enumerated: false … ``` (unnumbered, #113)
    - $$\\begin{align} ... \\end{align}$$
      → $$ \\begin{aligned} ... \\end{aligned} $$ (label)
    - $$\\begin{align*} ... \\end{align*}$$
      → ```{math} :enumerated: false \\begin{aligned} … ``` (unnumbered, #113)
    """
    # Pattern: $$\begin{equation} ... \end{equation}$$ with optional \label.
    # The label may appear before, after, or interleaved with the body —
    # all three conventions exist in real LaTeX manuscripts. Extracting the
    # label here is what keeps any orphan `\label{}` from surviving into
    # the document body, where the catch-all standalone-label regex
    # (further down) could otherwise span paragraphs and swallow content.
    def replace_equation(m):
        star = m.group(1)
        body = m.group(2).strip()
        lbl = re.search(r'\\label\{([^}]+)\}', body)
        label = None
        if lbl:
            body = (body[:lbl.start()] + body[lbl.end():]).strip()
            label = convert_label_colons(lbl.group(1))
        # ``equation*`` is unnumbered in LaTeX — emit a forced-unnumbered
        # block so book-wide numbering doesn't number it (#113). A plain
        # ``equation`` (numbered in LaTeX) keeps the bare ``$$`` form, which
        # mystmd numbers — matching LaTeX whether or not it carries a label.
        #
        # BAIL for a body carrying ``\begin{tikzcd}``: the consumer-side
        # ``TIKZCD_INLINE_MAP`` (resolve_tikz_figures) matches the bare
        # ``$$ … tikzcd … $$`` shape and replaces the block with an image —
        # the ``{math}`` form broke that match, leaking tikzcd to KaTeX and
        # losing the mapped figure (found in the dp1 ch_fps build test).
        if star and '\\begin{tikzcd}' not in body:
            return _emit_unnumbered_math(body, label)
        if label:
            return f'$$\n{body}\n$$ ({label})'
        return f'$$\n{body}\n$$'

    text = re.sub(
        r'\$\$\\begin\{equation(\*?)\}\s*(.*?)\\end\{equation\*?\}\$\$',
        replace_equation,
        text,
        flags=re.DOTALL
    )

    def replace_unlabeled_equation(m):
        content = m.group(1).strip()
        return f'$$\n{content}\n$$'

    def _extract_math_labels(content: str) -> tuple[str, list[str]]:
        """Pull every ``\\label{...}`` out of a math-env body and return
        the stripped body plus the list of labels in source order. Used
        by ``align`` (closes #30) and ``multline`` / ``gather`` (closes
        #37). Per-row labels — and the standard "label at end of body"
        convention for ``multline`` — otherwise survive into MyST as
        bare ``\\label{}`` tokens that KaTeX silently drops, leaving
        any ``\\eqref{}`` to the row unresolved."""
        labels = re.findall(r'\\label\{([^}]+)\}', content)
        content = re.sub(r'\\label\{[^}]+\}', '', content).strip()
        return content, labels

    # Per-row align handling (#70 / #46) ────────────────────────────────
    #
    # When an align body has 2+ per-row ``\label{}`` calls OR 2+
    # per-row ``\tag*{}`` calls, keeping the whole body inside one
    # ``\begin{aligned}`` block breaks downstream rendering:
    #
    # - MyST collapses N consecutive ``(name)=`` anchors stacked above
    #   a single block to ONE anchor (only the first survives, the
    #   rest get renamed and any cross-ref to them dangles — #70).
    # - KaTeX errors with ``Multiple \\tag`` because ``\\tag*{}`` is
    #   limited to one per equation env, and ``aligned`` counts as
    #   one (#46).
    #
    # The fix: split per ``\\`` row into separate ``$$...$$`` blocks
    # each with its own trailing label / inline ``\\tag*{}``. Cost:
    # the LaTeX-side ``&`` column alignment is lost (replaced with
    # whitespace). For independent equations grouped in an align for
    # spacing this is acceptable; for tabular layouts it's a cosmetic
    # degradation we accept in exchange for correct cross-refs and
    # working KaTeX rendering.

    def _align_needs_split(body: str) -> bool:
        """``True`` when the body has 2+ per-row labels or 2+ per-row
        ``\\tag*{}`` calls — the collision triggers from #70 / #46."""
        n_labels = len(re.findall(r'\\label\{', body))
        n_tags = len(re.findall(r'\\tag\*?\{', body))
        return n_labels >= 2 or n_tags >= 2

    def _split_align_rows(body: str) -> list[tuple[str, list[str]]]:
        """Split an align body on ``\\\\`` row terminators. Return
        per-row ``(content_clean, [labels])`` tuples. ``content_clean``
        has ``\\label{}`` calls stripped, ``&`` alignment markers
        replaced with whitespace, and bridging trailing punctuation
        (``,``, ``;``) removed (a common LaTeX convention is
        ``y = x + 1, \\label{eq:foo}`` where the comma is a
        sentence-style separator, not part of the equation)."""
        pieces = re.split(r'\\\\(?:\[[^\]]*\])?', body)
        rows: list[tuple[str, list[str]]] = []
        for piece in pieces:
            row = piece.strip()
            if not row:
                continue
            labels = re.findall(r'\\label\{([^}]+)\}', row)
            row = re.sub(r'\\label\{[^}]+\}', '', row).strip()
            row = re.sub(r'\s*(?<!\\)&\s*', ' ', row).strip()
            row = re.sub(r'[,;]\s*$', '', row).strip()
            rows.append((row, labels))
        return rows

    def _emit_split_align(body: str, leading_label: str | None = None,
                          starred: bool = False) -> str:
        """Emit one block per row, each with its own label (when present). A
        leading ``\\begin{align}\\label{}`` becomes a ``(name)=`` anchor above
        the first row block. When ``starred`` (an ``align*`` that hit the split
        path), each row is a forced-unnumbered ``{math}`` directive so the rows
        don't consume equation numbers under book-wide numbering (#113)."""
        rows = _split_align_rows(body)
        out_blocks: list[str] = []
        for i, (content, labels) in enumerate(rows):
            if starred:
                primary = convert_label_colons(labels[0]) if labels else None
                block = _emit_unnumbered_math(content, primary)
                for extra in labels[1:]:
                    block = f'({convert_label_colons(extra)})=\n\n{block}'
            elif labels:
                primary = convert_label_colons(labels[0])
                block = f'$$\n{content}\n$$ ({primary})'
                # Multiple labels on the same row are rare but legal —
                # stack any extras as ``(name)=`` anchors (one anchor
                # → no collision risk).
                for extra in labels[1:]:
                    block = f'({convert_label_colons(extra)})=\n\n{block}'
            else:
                block = f'$$\n{content}\n$$'
            if i == 0 and leading_label:
                block = f'({convert_label_colons(leading_label)})=\n\n{block}'
            out_blocks.append(block)
        result = '\n\n'.join(out_blocks)
        # If the joined output begins with a ``(name)=`` anchor (from
        # ``leading_label`` or from the first row's stacked extras),
        # prepend ``\n\n`` so MyST parses it as a block-level anchor
        # rather than fusing it into the preceding prose paragraph —
        # mirrors the labeled-align extra-anchor path's leading
        # ``\n\n``. Caught by Copilot review on PR #77.
        if result.startswith('('):
            result = f'\n\n{result}'
        return result

    # Pattern: $$\begin{align}\label{...} ... \end{align}$$
    # Leading label becomes the trailing ``(label)`` for the block; up
    # to one per-row label stacks as an anchor above. Beyond that the
    # split path takes over (#70).
    def replace_labeled_align(m):
        leading = m.group(1)
        body = m.group(2)
        if _align_needs_split(body):
            return _emit_split_align(body, leading_label=leading)
        content, extra = _extract_math_labels(body.strip())
        leading_decoded = convert_label_colons(leading)
        block = f'$$\n\\begin{{aligned}}\n{content}\n\\end{{aligned}}\n$$ ({leading_decoded})'
        if extra:
            anchors = '\n'.join(f'({convert_label_colons(lbl)})=' for lbl in extra)
            return f'\n\n{anchors}\n\n{block}'
        return block

    text = re.sub(
        r'\$\$\\begin\{align\}\s*\\label\{([^}]+)\}\s*(.*?)\\end\{align\}\$\$',
        replace_labeled_align,
        text,
        flags=re.DOTALL
    )

    # Pattern: $$\begin{align*} ... \end{align*}$$ (unlabeled at the env
    # level, may carry an inner \label{} per #48 — emit as explicit anchor
    # form with surrounding blank lines so MyST parses it as a block-level
    # anchor rather than fusing it into the preceding prose paragraph).
    # The split path takes over when the body has 2+ labels or 2+ tags (#70 / #46).
    def replace_unlabeled_align(m):
        star = m.group(1)
        body = m.group(2)
        if _align_needs_split(body):
            return _emit_split_align(body, starred=bool(star))
        content, labels = _extract_math_labels(body.strip())
        aligned = f'\\begin{{aligned}}\n{content}\n\\end{{aligned}}'
        # ``align*`` is unnumbered in LaTeX; emit a forced-unnumbered block
        # (#113). A plain ``align`` (numbered in LaTeX) keeps the bare ``$$``
        # form so book-wide numbering numbers it. tikzcd bodies bail to the
        # bare form so TIKZCD_INLINE_MAP keeps matching (dp1 ch_fps).
        if star and '\\begin{tikzcd}' not in content:
            block = _emit_unnumbered_math(aligned)
        else:
            block = f'$$\n{aligned}\n$$'
        if labels:
            anchors = '\n'.join(f'({convert_label_colons(lbl)})=' for lbl in labels)
            return f'\n\n{anchors}\n\n{block}'
        return block

    text = re.sub(
        r'\$\$\\begin\{align(\*?)\}\s*(.*?)\\end\{align\*?\}\$\$',
        replace_unlabeled_align,
        text,
        flags=re.DOTALL
    )

    # multline + gather: one unified handler. Collapse the previous
    # labeled / unlabeled pair into a single pass that extracts
    # ``\label{}`` from anywhere in the body — the standard LaTeX
    # convention for ``multline`` puts the label *at the end* of the
    # body, which the leading-label-only regex would miss (closes
    # #37). Same shape of fix that #30 applied to align. First label
    # becomes the block's trailing ``(label)`` for backward-compat;
    # any additional labels (legitimate per-row in ``gather``) stack
    # as anchors above.
    def replace_math_block(m):
        star = m.group(1)
        content, labels = _extract_math_labels(m.group(2).strip())
        # Starred multline*/gather* is unnumbered in LaTeX (#113) — emit a
        # forced-unnumbered {math} directive REGARDLESS of label presence (a
        # stray \label in a starred env still must not consume a number). The
        # first label becomes :label:, any extras stack as anchors above.
        # tikzcd bodies bail to the bare form (TIKZCD_INLINE_MAP match).
        if star and '\\begin{tikzcd}' not in content:
            primary = convert_label_colons(labels[0]) if labels else None
            block = _emit_unnumbered_math(content, primary)
            extra = labels[1:]
            if extra:
                anchors = '\n'.join(f'({convert_label_colons(lbl)})=' for lbl in extra)
                return f'\n\n{anchors}\n\n{block}'
            return block
        block = f'$$\n{content}\n$$'
        if not labels:
            return block
        leading = convert_label_colons(labels[0])
        block = f'{block} ({leading})'
        extra = labels[1:]
        if extra:
            anchors = '\n'.join(f'({convert_label_colons(lbl)})=' for lbl in extra)
            return f'\n\n{anchors}\n\n{block}'
        return block

    text = re.sub(
        r'\$\$\\begin\{multline(\*?)\}\s*(.*?)\\end\{multline\*?\}\$\$',
        replace_math_block,
        text,
        flags=re.DOTALL
    )

    text = re.sub(
        r'\$\$\\begin\{gather(\*?)\}\s*(.*?)\\end\{gather\*?\}\$\$',
        replace_math_block,
        text,
        flags=re.DOTALL
    )

    # Standalone $$math\label{eq:foo}$$ on a single line. Must stay
    # single-line: a DOTALL match here would pair the nearest preceding $$
    # with the orphan \label{}, regardless of how many paragraphs (and
    # {figure}/{prf:remark}/… directives) sit between them. See GH #26.
    text = re.sub(
        r'\$\$([^\n]*?)\\label\{([^}]+)\}([^\n]*?)\$\$',
        lambda m: f'$$\n{(m.group(1) + m.group(3)).strip()}\n$$ ({convert_label_colons(m.group(2))})',
        text,
    )

    # Ensure $$ (label) is on its own line — pandoc's --wrap=none can leave
    # trailing text on the same line, preventing MyST from recognizing labels.
    # Only match horizontal whitespace after the label (not newlines).
    text = re.sub(
        r'(\$\$ \([^)]+\))[ \t]+(\S)',
        r'\1\n\2',
        text
    )

    # Ensure bare closing $$ (no label) is separated from trailing text.
    # Match $$ at start of line, followed by space then text, but NOT a label.
    # Labels look like (identifier) — skip those with negative lookahead.
    text = re.sub(
        r'^(\$\$)[ \t]+(?!\([a-zA-Z0-9_-]+\))(\S)',
        r'\1\n\2',
        text,
        flags=re.MULTILINE
    )

    # Ensure opening $$ of equation blocks is separated from preceding text.
    # Match: any non-newline char, horizontal whitespace, then $$ followed by
    # newline. Allows the preceding char to be ``$`` — pandoc routinely emits
    # ``$\Xsf$ $$`` when an inline-math closer abuts a display-math opener;
    # without this, the opener sticks to the prose line and MyST treats the
    # whole thing as inline math, throwing the block state-machine downstream
    # into the wrong mode and stripping blank lines for the rest of the file.
    text = re.sub(
        r'([^\n])[ \t]+\$\$\n',
        r'\1\n\n$$\n',
        text
    )

    # Hoist any ```{math} directive (starred env, #113) that ended up abutting
    # prose onto its own block.
    text = _blockify_math_directives(text)

    # Remove blank lines inside $$ blocks.
    # MyST treats blank lines as ending a math block, so:
    #   $$
    #   content
    #                  ← this blank line breaks the math
    #   $$
    # Fix by removing blank lines while inside a $$ block.
    lines = text.split('\n')
    result = []
    in_math = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith('$$') and not in_math:
            in_math = True
            result.append(line)
        elif in_math:
            if stripped.startswith('$$'):
                # Closing $$ (possibly with label like "$$ (eq-foo)")
                in_math = False
                result.append(line)
            elif stripped == '':
                # Skip blank lines inside math blocks
                continue
            else:
                result.append(line)
        else:
            result.append(line)
    text = '\n'.join(result)

    return text


def join_split_inline_math(text: str) -> str:
    """Join inline math expressions split across lines where the next line
    begins with a Markdown block-structure token (`>`, or a list marker).

    Pandoc preserves LaTeX source line wraps, so a snippet like

        ... we require that $r
        > 0$ and ...

    becomes two lines in markdown. MyST then parses the leading `>` as a
    blockquote marker, breaking both the math and the surrounding paragraph.
    The same applies to a continuation line starting with a list-marker
    token (#141) — dp1 ch_fps wraps ``$u\\n+ c \\in U$`` and the ``+ ``
    opens a bullet item, splitting the ``$...$`` span across two blocks
    so neither half parses as math. Detect odd-parity unescaped `$` on a
    line followed by a line starting with `>`, `+ `, `- `, `* `, or
    ``N. `` / ``N) `` and merge them with a single space.

    Skips fenced code blocks (```) and display math blocks ($$) so genuine
    blockquotes and lists are left alone.
    """
    lines = text.split('\n')
    out: list[str] = []
    in_fence = False
    in_math_block = False
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if stripped.startswith('```'):
            in_fence = not in_fence
            out.append(line)
            i += 1
            continue
        if in_fence:
            out.append(line)
            i += 1
            continue
        if stripped.startswith('$$'):
            in_math_block = not in_math_block
            out.append(line)
            i += 1
            continue
        if in_math_block:
            out.append(line)
            i += 1
            continue

        clean = line.replace('\\$', '').replace('$$', '')
        if clean.count('$') % 2 == 1 and i + 1 < len(lines):
            next_stripped = lines[i + 1].lstrip()
            if next_stripped.startswith('>') or re.match(
                r'(?:[+\-*]|\d+[.)])\s', next_stripped
            ):
                # The line ends inside an open ``$...$`` span, so the
                # leading token is a math operator (``+``/``-``/``*``)
                # or plain text — not a blockquote or list marker.
                out.append(line.rstrip() + ' ' + next_stripped)
                i += 2
                continue
        out.append(line)
        i += 1
    return '\n'.join(out)


def strip_blank_lines_in_math(text: str) -> str:
    """Collapse internal blank lines inside display-math blocks.

    Pandoc preserves the LaTeX source's whitespace formatting verbatim,
    and ``cleanup_typography`` strips ``\\qedhere`` (and a few other
    constructs) AFTER ``convert_equations``. The result is a
    whitespace-only line inside an otherwise valid ``$$ … $$`` block,
    e.g.::

        $$
        \\tau s(A)
                = …
                = s(\\tau A).
                ←  this line is all whitespace (was ``        \\qedhere``)
        $$ (eq-foo)

    MyST treats the trailing whitespace-only line + the empty math
    region behind it as a separate empty math node and emits a hard
    ``No input for math node`` error (issue #11).

    Collapse any run of blank/whitespace-only lines inside a ``$$ … $$``
    block down to a single newline, and strip leading/trailing
    whitespace from the body. Closes-with-label form
    (``$$ (eq-foo)``) is preserved — the regex only looks at the body
    between the two ``$$`` delimiters.
    """
    def _strip(m: re.Match) -> str:
        body = re.sub(r'\n\s*\n+', '\n', m.group(1))
        return f'$$\n{body.strip()}\n$$'

    # Anchor the opening ``$$`` to a line start (MULTILINE ``^``) — an
    # inline-closing ``$$`` at end-of-line (e.g. ``- text $$x$$\n- next``)
    # has its ``$$`` mid-line and must not be matched as a block opener;
    # otherwise ``(.*?)`` extends across unrelated prose / list items
    # until it finds the next genuine ``\n$$``, collapsing every blank
    # line in between (issue #12).
    return re.sub(
        r'^\$\$\n(.*?)\n\$\$', _strip, text, flags=re.MULTILINE | re.DOTALL
    )


def ensure_blank_after_display_math(text: str) -> str:
    """Ensure a blank line follows the closing ``$$`` of every display-math block.

    Pandoc emits display math followed immediately by the next prose paragraph.
    MyST renders this fine but the source is harder to read, and some renderers
    attach the next paragraph too tightly. Inserting a blank line keeps output
    identical while improving source readability.

    Skips fenced code blocks. Tracks display-math state so the rule fires only
    on the closing delimiter, not the opening one.
    """
    lines = text.split('\n')
    out: list[str] = []
    in_fence = False
    in_math_block = False
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith('```'):
            in_fence = not in_fence
            out.append(line)
            continue
        if in_fence:
            out.append(line)
            continue
        # Display-math delimiter: first non-whitespace token is `$$`, optionally
        # followed by ` (label)` on the closing line.
        is_dm_delim = (
            stripped == '$$'
            or stripped.startswith('$$ ')
            or stripped.startswith('$$(')
        )
        if is_dm_delim:
            was_open = in_math_block
            in_math_block = not in_math_block
            out.append(line)
            # If this was the closing delimiter, ensure next line is blank.
            if was_open and i + 1 < len(lines) and lines[i + 1].strip() != '':
                out.append('')
            continue
        out.append(line)
    return '\n'.join(out)
