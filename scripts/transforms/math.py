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


def _emit_tagged_math(content: str, label: str | None, enumerator: str,
                      unnumbered: bool = False) -> str:
    """Emit display math whose equation identifier is a LaTeX ``\\tag`` text
    rather than an auto-number (issue #192).

    ``\\tag{}`` / ``\\tag*{}`` *replace* a row's number in amsmath and do not
    advance the counter. Left in the body they render alongside the number
    mystmd assigns, so the reader sees both. mystmd's ``:enumerator:`` is the
    only field that sets a literal identifier without advancing the counter
    (``ReferenceState.incrementCount`` returns early once ``node.enumerator``
    is set), and it is what a ``{eq}`` cross-reference renders — so lifting
    the tag there keeps the tag, the count and the refs all correct."""
    lines = ['```{math}']
    if label:
        lines.append(f':label: {label}')
    if unnumbered:
        lines.append(':enumerated: false')
    lines.append(f':enumerator: {enumerator}')
    lines.append('')
    lines.append(content)
    lines.append('```')
    return '\n'.join(lines)


# amsmath row-numbering tokens (#192). Neither mystmd nor KaTeX models them:
# KaTeX silently swallows ``\nonumber`` / ``\notag``, and a ``\tag`` inside an
# emitted block renders *next to* the auto-number instead of replacing it. The
# converter therefore has to resolve both before emission.
_AMSMATH_NONUMBER_RE = re.compile(r'\\(?:nonumber|notag)(?![a-zA-Z])')
_AMSMATH_TAG_RE = re.compile(r'\\tag\*?\s*\{')


def _strip_nonumber_tokens(text: str) -> str:
    """Drop ``\\nonumber`` / ``\\notag``. Once the converter has decided
    whether the block is numbered the token carries no further meaning, and
    leaving it in ships a stray control sequence into published math."""
    return _AMSMATH_NONUMBER_RE.sub('', text)


def _extract_row_tag(row: str) -> tuple[str, str | None]:
    """Split a ``\\tag{…}`` / ``\\tag*{…}`` off ``row``, returning the row
    without it plus the raw brace payload (``None`` when absent).

    Brace-matched rather than regex-terminated so a nested payload such as
    ``\\tag*{\\text{(atm.\\ carbon)}}`` comes back whole."""
    m = _AMSMATH_TAG_RE.search(row)
    if not m:
        return row, None
    open_brace = m.end() - 1
    depth = 0
    for i in range(open_brace, len(row)):
        if row[i] == '{':
            depth += 1
        elif row[i] == '}':
            depth -= 1
            if depth == 0:
                return (row[:m.start()] + row[i + 1:]), row[open_brace + 1:i]
    return row, None


def _normalize_tag_text(payload: str) -> str | None:
    """Reduce a ``\\tag`` payload to a literal ``:enumerator:`` value, or
    ``None`` when it cannot be represented as plain text.

    ``:enumerator:`` is a plain-text field which mystmd wraps in the equation
    template ``(%s)``, so the parens of the usual LaTeX convention
    ``\\tag*{\\text{(budget)}}`` have to come off or the reader gets
    ``((budget))``. Order is load-bearing: unwrap, strip parens, resolve text
    escapes, and only *then* bail — payloads like ``\\text{(atm.\\ carbon)}``
    (real, dp-deep-learning ch11) still carry a ``\\ `` at the point where an
    earlier bail would reject them."""
    s = payload.strip()
    while True:
        m = re.fullmatch(r'\\(?:text|textrm|mathrm|mbox)\s*\{(.*)\}', s, re.DOTALL)
        if not m:
            break
        s = m.group(1).strip()
    if s.startswith('(') and s.endswith(')'):
        s = s[1:-1].strip()
    s = s.replace('\\ ', ' ').replace('~', ' ')
    s = s.replace('---', '\u2014').replace('--', '\u2013')
    s = re.sub(r'\s+', ' ', s).strip()
    # An *empty* ``:enumerator:`` is silently ignored by mystmd, which would
    # hand the block a real number again; a residual control sequence or math
    # shift would render literally. Both fall back to the caller's shape.
    if not s or '\\' in s or '$' in s:
        return None
    return s


def _lift_tag(content: str) -> tuple[str, str | None]:
    """Lift a representable ``\\tag`` out of a math body, returning the body
    without it plus the literal enumerator. Leaves the body untouched (and
    returns ``None``) when the tag text cannot be represented — the caller
    then keeps the tag in the body and forces the block unnumbered."""
    stripped, raw = _extract_row_tag(content)
    if raw is None:
        return content, None
    normalized = _normalize_tag_text(raw)
    if normalized is None:
        return content, None
    return stripped.strip(), normalized


# ── #193: depth-aware math-row scanner ────────────────────────────────────
_CONTROL_WORD_RE = re.compile(r'\\[a-zA-Z]+')
_INTERTEXT_RE = re.compile(r'\\(?:short)?intertext\s*\{')


def _scan_top_level(text: str):
    r"""Yield ``(kind, start, end)`` for every *depth-0* structural token."""
    i, n = 0, len(text)
    env_depth = brace_depth = 0
    while i < n:
        c = text[i]
        if c == '\\':
            nxt = text[i + 1] if i + 1 < n else ''
            if nxt == '\\':
                j = i + 2
                if j < n and text[j] == '*':
                    j += 1
                if j < n and text[j] == '[':
                    close = text.find(']', j)
                    if close != -1:
                        j = close + 1
                if env_depth == 0 and brace_depth == 0:
                    yield ('rowbreak', i, j)
                i = j
                continue
            m = _CONTROL_WORD_RE.match(text, i)
            if m:
                j = m.end()
                if m.group(0) in ('\\begin', '\\end'):
                    k = j
                    while k < n and text[k] in ' \t\n':
                        k += 1
                    if k < n and text[k] == '{':
                        close = text.find('}', k)
                        if close != -1:
                            env_depth += 1 if m.group(0) == '\\begin' else -1
                            if env_depth < 0:
                                env_depth = 0
                            j = close + 1
                i = j
                continue
            i += 2
            continue
        if c == '%':
            nl = text.find('\n', i)
            i = n if nl == -1 else nl + 1
            continue
        if c == '{':
            brace_depth += 1
        elif c == '}':
            brace_depth = max(brace_depth - 1, 0)
        elif c == '&' and env_depth == 0 and brace_depth == 0:
            yield ('amp', i, i + 1)
        i += 1


def _split_math_rows(body: str) -> list[str]:
    rows, start = [], 0
    for kind, s, e in _scan_top_level(body):
        if kind == 'rowbreak':
            rows.append(body[start:s])
            start = e
    rows.append(body[start:])
    return rows


def _neutralize_top_level_amps(row: str) -> str:
    out: list[str] = []
    pos = 0
    for kind, s, e in _scan_top_level(row):
        if kind != 'amp':
            continue
        a = s
        while a > pos and row[a - 1] in ' \t\n':
            a -= 1
        b = e
        while b < len(row) and row[b] in ' \t\n':
            b += 1
        out.append(row[pos:a])
        out.append(' ')
        pos = b
    out.append(row[pos:])
    return ''.join(out).strip()


def _renderable(content: str) -> str:
    r"""The part of a row that would actually typeset. A row reduced to
    nothing but ``%`` comments still looks non-empty to a naive truth test,
    but renders as an empty equation and draws a mystmd ``commentAtEnd``
    warning, so it counts as empty here.

    Every "is there anything here?" test goes through this — the empty-row
    test and ``_mathless`` both — so that a comment is non-rendering
    everywhere rather than only where someone remembered."""
    return re.sub(r'(?<!\\)%.*$', '', content, flags=re.MULTILINE).strip()


def _mathless(fragment: str) -> str:
    """Reduce a row fragment to the characters that would actually render —
    used only to decide whether an ``\\intertext`` had any real math before
    it in its row."""
    fragment = _AMSMATH_NONUMBER_RE.sub('', fragment)
    fragment = re.sub(r'\\label\{[^}]*\}', '', fragment)
    fragment = re.sub(r'\\tag\*?\s*\{[^}]*\}', '', fragment)
    return _renderable(fragment.replace('&', ''))


def _extract_intertext(row: str) -> tuple[str, list[tuple[bool, str]]]:
    """Strip every ``\\intertext{}`` / ``\\shortintertext{}`` out of ``row``,
    returning the row without them plus ``(leading, payload)`` pairs.
    ``leading`` is ``True`` when nothing renderable preceded the macro in the
    row — amsmath's canonical position, right after a ``\\\\``."""
    found: list[tuple[bool, str]] = []
    while True:
        m = _INTERTEXT_RE.search(row)
        if not m:
            return row, found
        open_brace = m.end() - 1
        depth = 0
        end = None
        for i in range(open_brace, len(row)):
            if row[i] == '{':
                depth += 1
            elif row[i] == '}':
                depth -= 1
                if depth == 0:
                    end = i
                    break
        if end is None:
            return row, found
        found.append((not _mathless(row[:m.start()]),
                      row[open_brace + 1:end].strip()))
        row = row[:m.start()] + row[end + 1:]


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
    - $$ ... $$ / \\[ ... \\] (plain TeX display math, no env wrapper)
      → ```{math} :enumerated: false … ``` (unnumbered, #167)
    """
    # Plain TeX display math — bare ``$$ … $$`` and ``\[ … \]``. Pandoc emits
    # BOTH as a bare ``$$ … $$`` with no ``\begin{equation}`` wrapper, and both
    # are UNNUMBERED in LaTeX. But mystmd assigns a bare ``$$`` an equation
    # number under book-wide numbering (``numbering: book: true`` /
    # ``equation: true``) — inventing a number that isn't in the PDF and
    # shifting every later equation by +1 (#167). Emit them as a
    # forced-unnumbered ``{math}`` directive, the same treatment ``equation*``
    # already gets (#113).
    #
    # This MUST run before the ``\begin{equation}``-env patterns below: a
    # numbered ``equation`` keeps its ``\begin{}`` wrapper through pandoc and is
    # rewritten to a bare ``$$`` *here in this same pass*, after which it is
    # indistinguishable from genuine plain display math. So the wrapper is the
    # only signal — bail on any body that is a numbered top-level env (handled
    # by those patterns) and leave it untouched for them. Also bail on a
    # ``\begin{tikzcd}`` body (the consumer ``TIKZCD_INLINE_MAP`` matches the
    # bare ``$$ … tikzcd … $$`` shape) and on a ``\label{}`` / ``\tag`` body
    # (a numbered-with-label form the single-line label pass handles below).
    # Inner unnumbered envs (``aligned`` / ``cases`` / ``split`` / ``array`` …
    # from ``\[\begin{aligned}…\]``) are NOT bailed — they stay plain.
    _NUMBERED_ENV_RE = re.compile(
        r'\\begin\{(?:equation|align|gather|multline|flalign|eqnarray|alignat)\*?\}'
    )

    def replace_plain_display(m):
        body = m.group(1).strip()
        if (_NUMBERED_ENV_RE.match(body)
                or '\\begin{tikzcd}' in body
                or '\\label{' in body
                or '\\tag' in body):
            return m.group(0)
        return _emit_unnumbered_math(body)

    text = re.sub(r'\$\$(.*?)\$\$', replace_plain_display, text, flags=re.DOTALL)

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
        body = _strip_nonumber_tokens(body)
        body, enumerator = _lift_tag(body)
        if enumerator and '\\begin{tikzcd}' not in body:
            return _emit_tagged_math(body, label, enumerator,
                                     unnumbered=bool(star))
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
        # Share the emission-side tag pattern rather than a second copy of
        # it: TeX skips whitespace between a control sequence and its
        # argument, so ``\tag* {…}`` is legal. Counting with a tighter regex
        # than the one that later *lifts* the tag let a spaced body slip past
        # the split path and collapse, stranding the second tag raw in the
        # body next to the first one's ``:enumerator:``.
        n_tags = len(_AMSMATH_TAG_RE.findall(body))
        if _INTERTEXT_RE.search(body):
            return True
        return n_labels >= 2 or n_tags >= 2

    def _make_row_group(group: list[str]) -> dict:
        """Build one emittable block from a list of source rows.

        A single-row group gets the historical cleaners: ``&`` alignment
        markers become whitespace and bridging trailing punctuation is
        dropped (``y = x + 1, \\label{eq:foo}`` — the comma is
        sentence-style, not part of the equation). A *fused* group keeps
        both: its ``&`` columns and its trailing punctuation sit **inside**
        one equation, where they are content rather than row-separator
        artefacts."""
        unnumbered = bool(_AMSMATH_NONUMBER_RE.search(group[-1]))
        fused = len(group) > 1
        labels: list[str] = []
        enumerator: str | None = None
        tag_in_body = False
        cleaned: list[str] = []
        pre_prose: list[str] = []
        post_prose: list[str] = []
        seen_content = False
        for piece in group:
            piece = _strip_nonumber_tokens(piece)
            piece, prose = _extract_intertext(piece)
            if _AMSMATH_TAG_RE.search(piece):
                piece, lifted = _lift_tag(piece)
                if lifted is None:
                    tag_in_body = True
                elif enumerator is None:
                    enumerator = lifted
            labels.extend(re.findall(r'\\label\{([^}]+)\}', piece))
            piece = re.sub(r'\\label\{[^}]+\}', '', piece).strip()
            for leading, payload in prose:
                target = pre_prose if (leading and not seen_content) else post_prose
                target.append(payload)
            seen_content = seen_content or bool(_renderable(piece))
            cleaned.append(piece)
        if fused:
            body = ' \\\\\n'.join(p for p in cleaned if p)
            content = (f'\\begin{{aligned}}\n{body}\n\\end{{aligned}}'
                       if body.strip() else '')
        else:
            content = _neutralize_top_level_amps(cleaned[0])
            content = re.sub(r'(?<!\\)[,;]\s*$', '', content).strip()
        return {'content': content, 'labels': labels, 'enumerator': enumerator,
                'tag_in_body': tag_in_body, 'unnumbered': unnumbered,
                'pre_prose': pre_prose, 'post_prose': post_prose}

    def _split_align_rows(body: str) -> list[dict]:
        """Split an align body on ``\\\\`` row terminators into emittable
        groups — normally one per row.

        A row carrying ``\\nonumber`` / ``\\notag`` is **fused forward** into
        the row that follows it (transitively, for chains) rather than
        becoming its own block. amsmath drops such a row's number, and in
        practice it is a continuation of the next row's expression, so
        splitting there tore one equation into two blocks with unbalanced
        delimiters and left every ``\\eqref`` to it pointing at the tail
        fragment (#192). A trailing ``\\nonumber`` row has nothing to fuse
        into and is emitted forced-unnumbered instead."""
        pieces = [p for p in _split_math_rows(body) if p.strip()]

        groups: list[list[str]] = []
        pending: list[str] = []
        for piece in pieces:
            pending.append(piece)
            if not _AMSMATH_NONUMBER_RE.search(piece):
                groups.append(pending)
                pending = []
        if pending:
            groups.append(pending)

        rows: list[dict] = []
        for group in groups:
            # Two ``\tag``s inside one ``aligned`` is a hard KaTeX
            # ``Multiple \tag`` failure — the #46 collision this split path
            # exists to avoid. Never fuse rows into that shape.
            if len(group) > 1 and sum(
                    1 for p in group if _AMSMATH_TAG_RE.search(p)) > 1:
                rows.extend(_make_row_group([piece]) for piece in group)
            else:
                rows.append(_make_row_group(group))
        # Emptiness is decided HERE, after every stripper has run — a row
        # that was non-empty in the source can be empty by now (it held only
        # a ``\label{}``, or only a ``%`` comment). Testing before stripping
        # let such a row through as ``$$\n\n$$ (eq-x)``, which mystmd rejects
        # with "No input for math node" while still consuming a number.
        kept: list[dict] = []
        for row in rows:
            if _renderable(row['content']):
                kept.append(row)
            elif row['labels'] or row['enumerator'] or row['tag_in_body']:
                # Nothing left to typeset, but the row still carries an
                # identifier, so it cannot just be dropped — that would
                # dangle every reference to it. An empty group is valid
                # KaTeX and keeps the anchor addressable.
                row['content'] = '{}'
                kept.append(row)
            elif row['pre_prose'] or row['post_prose']:
                # An ``\intertext``-only row. Keep it so the prose survives;
                # ``_emit_split_align`` emits the prose and no math block.
                row['content'] = ''
                kept.append(row)
            # Anything else is genuinely empty and carries nothing to
            # preserve — drop it. Note this does NOT reproduce LaTeX's
            # numbering of an empty row; see lesson 056.
        return kept

    def _emit_split_align(body: str, leading_label: str | None = None,
                          starred: bool = False) -> str:
        """Emit one block per row, each with its own label (when present). A
        leading ``\\begin{align}\\label{}`` becomes a ``(name)=`` anchor above
        the first row block. When ``starred`` (an ``align*`` that hit the split
        path), each row is a forced-unnumbered ``{math}`` directive so the rows
        don't consume equation numbers under book-wide numbering (#113)."""
        rows = _split_align_rows(body)
        out_blocks: list[str] = []
        # The leading ``\begin{align}\label{}`` anchor belongs above the first
        # row that actually emits a block — an ``\intertext``-only row ahead
        # of it produces prose, which an anchor must not attach to.
        leading_pending = leading_label
        for row in rows:
            out_blocks.extend(row['pre_prose'])
            content = row['content']
            if content:
                labels = row['labels']
                primary = convert_label_colons(labels[0]) if labels else None
                if row['enumerator']:
                    # ``\tag`` replaces the number in LaTeX — lift it into the
                    # block's ``:enumerator:``, which mystmd does not count (#192).
                    block = _emit_tagged_math(content, primary, row['enumerator'],
                                              unnumbered=starred)
                elif starred or row['unnumbered'] or row['tag_in_body']:
                    # ``align*``; a trailing ``\nonumber`` row; or a tag we could
                    # not represent as literal text and so left in the body — all
                    # take no number, so force the block unnumbered rather than
                    # letting book-wide numbering invent one.
                    block = _emit_unnumbered_math(content, primary)
                elif primary:
                    block = f'$$\n{content}\n$$ ({primary})'
                else:
                    block = f'$$\n{content}\n$$'
                # Multiple labels on the same row are rare but legal —
                # stack any extras as ``(name)=`` anchors (one anchor
                # → no collision risk).
                for extra in labels[1:]:
                    block = f'({convert_label_colons(extra)})=\n\n{block}'
                if leading_pending:
                    block = (f'({convert_label_colons(leading_pending)})='
                             f'\n\n{block}')
                    leading_pending = None
                out_blocks.append(block)
            out_blocks.extend(row['post_prose'])
        if leading_pending and out_blocks:
            # Every row was prose-only — the anchor has no block to sit above,
            # but dropping it would dangle the outer label.
            out_blocks.insert(
                0, f'({convert_label_colons(leading_pending)})=')
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
        content = _strip_nonumber_tokens(content)
        content, enumerator = _lift_tag(content)
        leading_decoded = convert_label_colons(leading)
        aligned = f'\\begin{{aligned}}\n{content}\n\\end{{aligned}}'
        if enumerator:
            block = _emit_tagged_math(aligned, leading_decoded, enumerator)
        else:
            block = f'$$\n{aligned}\n$$ ({leading_decoded})'
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
        content = _strip_nonumber_tokens(content)
        content, enumerator = _lift_tag(content)
        aligned = f'\\begin{{aligned}}\n{content}\n\\end{{aligned}}'
        # ``align*`` is unnumbered in LaTeX; emit a forced-unnumbered block
        # (#113). A plain ``align`` (numbered in LaTeX) keeps the bare ``$$``
        # form so book-wide numbering numbers it. tikzcd bodies bail to the
        # bare form so TIKZCD_INLINE_MAP keeps matching (dp1 ch_fps).
        if enumerator and '\\begin{tikzcd}' not in content:
            block = _emit_tagged_math(aligned, None, enumerator,
                                      unnumbered=bool(star))
        elif star and '\\begin{tikzcd}' not in content:
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
        content = _strip_nonumber_tokens(content)
        content, enumerator = _lift_tag(content)
        # A ``\tag`` replaces the number rather than adding to it (#192).
        if enumerator and '\\begin{tikzcd}' not in content:
            primary = convert_label_colons(labels[0]) if labels else None
            block = _emit_tagged_math(content, primary, enumerator,
                                      unnumbered=bool(star))
            extra = labels[1:]
            if extra:
                anchors = '\n'.join(f'({convert_label_colons(lbl)})=' for lbl in extra)
                return f'\n\n{anchors}\n\n{block}'
            return block
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


def _inline_math_open_at_end(s: str) -> bool:
    r"""Return ``True`` when scanning ``s`` from outside math leaves an inline
    ``$…$`` span still open at the end of the line.

    Skips escaped ``\$``, inline-code backtick spans (so a lone ``$`` inside
    ``\`$HOME\``` isn't mistaken for a math delimiter), and ``$$`` display
    delimiters (which never open an inline span). A bare single ``$`` toggles
    the inline state. Used by ``collapse_inline_math_newlines`` to track an
    inline span ACROSS source lines — the per-line ``$``-parity count in
    ``join_split_inline_math`` is wrong precisely when a line both closes the
    span the previous line opened and opens a new one (even count, still
    open), which is the common ``$a\n…$ … $b\n…$`` wrap (#168)."""
    open_ = False
    j = 0
    n = len(s)
    while j < n:
        c = s[j]
        if c == '\\':
            j += 2          # skip the escaped char (incl. ``\$``)
            continue
        if c == '`':
            k = j
            while k < n and s[k] == '`':
                k += 1
            run = k - j
            close = s.find('`' * run, k)
            j = (close + run) if close != -1 else n
            continue
        if c == '$':
            if j + 1 < n and s[j + 1] == '$':
                j += 2      # ``$$`` display delimiter — not an inline toggle
                continue
            open_ = not open_
            j += 1
            continue
        j += 1
    return open_


def _update_fence_stack(stack: list[tuple[int, str]], line: str) -> bool:
    """Push/pop ``line`` on a backtick-fence ``stack`` of ``(ticks, kind)``;
    return ``True`` if ``line`` is a fence delimiter (opener or closer).

    ``kind`` is ``'code'`` for a plain code fence or a directive in
    ``_CODE_DIRECTIVE_NAMES`` (``code``/``code-cell``/…), else ``'content'``
    for any other ``{name}`` directive (``{prf:*}``, admonitions, …) whose
    body is prose/math the inline-math collapse must reach. Closers are
    matched by the stack (a bare run of ``≥`` the top opener's ticks), never
    by a second regex — the lesson-040 fence machine shared with
    ``fix_spacing_superscript``. A ``{prf:proof}`` opener is therefore NOT
    opaque, so an inline ``$…$`` span wrapping a hard line break inside a
    theorem/proof/example body still collapses (#174)."""
    m = _FENCE_LINE_RE.match(line.lstrip())
    if m is None:
        return False
    ticks = len(m.group(1))
    rest = m.group(2)
    if stack and rest.strip() == '' and ticks >= stack[-1][0]:
        stack.pop()
        return True
    rest_stripped = rest.lstrip()
    if rest_stripped.startswith('{'):
        close = rest_stripped.find('}')
        name = rest_stripped[1:close].strip() if close > 0 else ''
        first_word = name.split()[0] if name else ''
        kind = 'code' if first_word in _CODE_DIRECTIVE_NAMES else 'content'
    else:
        kind = 'code'  # plain code fence
    stack.append((ticks, kind))
    return True


def collapse_inline_math_newlines(text: str) -> str:
    r"""Collapse hard source line breaks that fall inside an inline ``$…$``
    span to a single space (#168).

    LaTeX treats a newline inside ``$…$`` as a space, but pandoc copies the
    break verbatim into the generated inline math, leaving spans like
    ``$T_\sigma v = \pi\n+ \beta Q v$``. MyST's dollarmath inline parser
    handles a ``$…$`` span containing a literal newline inconsistently — some
    parse, others fail and leak the raw ``$…$`` LaTeX as visible text in the
    HTML. Joining each split span onto one line (matching LaTeX's own
    whitespace semantics) removes the fragile pattern entirely, regardless of
    downstream parser quirks.

    This generalises ``join_split_inline_math`` (which only rescued a
    continuation line beginning with a block-structure token ``>`` / list
    marker) by tracking a **running cross-line** inline-math parity: whenever a
    prose line ends inside an open span, the next line is pulled up with a
    single space — repeatedly, so a span open across three or more lines
    collapses fully. Fence- and display-aware: only genuine *code* fences
    (plain ``` ``` ``` and ``_CODE_DIRECTIVE_NAMES`` directives) and
    ``$$ … $$`` display blocks are opaque — a *content* directive body
    (``{prf:proof}``, admonitions, …) IS descended into, so a span wrapping a
    hard break inside a theorem/proof/example collapses too (#174). Never
    merges into a fence opener, a display opener, or a blank line (a
    paragraph break — an inline span can't legally cross one).

    Display-delimiter detection mirrors ``ensure_blank_after_display_math`` —
    only a line that is exactly ``$$`` or opens ``$$ `` / ``$$(`` (the
    label-closer form) toggles the block state. A self-contained single-line
    ``$$x$$`` is NOT a block delimiter, so it doesn't flip the state and
    silently disable collapsing for the rest of the file (Copilot review)."""
    lines = text.split('\n')
    out: list[str] = []
    fence_stack: list[tuple[int, str]] = []
    in_math_block = False
    i = 0
    n = len(lines)
    while i < n:
        line = lines[i]
        stripped = line.strip()
        if _update_fence_stack(fence_stack, line):
            out.append(line)
            i += 1
            continue
        if fence_stack and fence_stack[-1][1] == 'code':
            out.append(line)
            i += 1
            continue
        is_dm_delim = (
            stripped == '$$'
            or stripped.startswith('$$ ')
            or stripped.startswith('$$(')
        )
        if is_dm_delim:
            in_math_block = not in_math_block
            out.append(line)
            i += 1
            continue
        if in_math_block:
            out.append(line)
            i += 1
            continue
        # Prose line: while it ends inside an open inline span, pull the next
        # line up with a single space.
        cur = line
        while _inline_math_open_at_end(cur) and i + 1 < n:
            nxt = lines[i + 1]
            nstripped = nxt.strip()
            if (nstripped == ''
                    or nstripped.startswith('```')
                    or nstripped.startswith('$$')):
                break
            cur = cur.rstrip() + ' ' + nxt.lstrip()
            i += 1
        out.append(cur)
        i += 1
    return '\n'.join(out)


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

    Skips genuine code fences (plain ``` ``` ``` / ``_CODE_DIRECTIVE_NAMES``
    directives) and display math blocks (``$$``) so blockquotes and lists are
    left alone; a content directive body (``{prf:*}``, admonitions) is still
    descended into (#174).
    """
    lines = text.split('\n')
    out: list[str] = []
    fence_stack: list[tuple[int, str]] = []
    in_math_block = False
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if _update_fence_stack(fence_stack, line):
            out.append(line)
            i += 1
            continue
        if fence_stack and fence_stack[-1][1] == 'code':
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
