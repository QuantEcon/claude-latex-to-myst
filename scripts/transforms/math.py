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


def convert_equations(text: str) -> str:
    """Convert pandoc equation blocks to MyST format.

    Patterns:
    - $$\\begin{equation}\\label{eq:foo} ... \\end{equation}$$
      → $$ ... $$ (eq-foo)
    - $$\\begin{equation*} ... \\end{equation*}$$
      → $$ ... $$
    - $$\\begin{align} ... \\end{align}$$
      → $$ \\begin{aligned} ... \\end{aligned} $$ (label)
    """
    # Pattern: $$\begin{equation} ... \end{equation}$$ with optional \label.
    # The label may appear before, after, or interleaved with the body —
    # all three conventions exist in real LaTeX manuscripts. Extracting the
    # label here is what keeps any orphan `\label{}` from surviving into
    # the document body, where the catch-all standalone-label regex
    # (further down) could otherwise span paragraphs and swallow content.
    def replace_equation(m):
        body = m.group(1).strip()
        lbl = re.search(r'\\label\{([^}]+)\}', body)
        if lbl:
            body = (body[:lbl.start()] + body[lbl.end():]).strip()
            return f'$$\n{body}\n$$ ({convert_label_colons(lbl.group(1))})'
        return f'$$\n{body}\n$$'

    text = re.sub(
        r'\$\$\\begin\{equation\*?\}\s*(.*?)\\end\{equation\*?\}\$\$',
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

    # Pattern: $$\begin{align}\label{...} ... \end{align}$$
    # The leading label becomes the trailing ``(label)`` for the block; any
    # additional per-row labels in the body are emitted as stacked anchors
    # above (multiple anchors targeting the same block — numbering
    # collapses but cross-refs all resolve).
    def replace_labeled_align(m):
        leading = convert_label_colons(m.group(1))
        content, extra = _extract_math_labels(m.group(2).strip())
        block = f'$$\n\\begin{{aligned}}\n{content}\n\\end{{aligned}}\n$$ ({leading})'
        if extra:
            anchors = '\n'.join(f'({convert_label_colons(lbl)})=' for lbl in extra)
            return f'{anchors}\n{block}'
        return block

    text = re.sub(
        r'\$\$\\begin\{align\}\s*\\label\{([^}]+)\}\s*(.*?)\\end\{align\}\$\$',
        replace_labeled_align,
        text,
        flags=re.DOTALL
    )

    # Pattern: $$\begin{align*} ... \end{align*}$$ (unlabeled)
    def replace_unlabeled_align(m):
        content, labels = _extract_math_labels(m.group(1).strip())
        block = f'$$\n\\begin{{aligned}}\n{content}\n\\end{{aligned}}\n$$'
        if labels:
            anchors = '\n'.join(f'({convert_label_colons(lbl)})=' for lbl in labels)
            return f'{anchors}\n{block}'
        return block

    text = re.sub(
        r'\$\$\\begin\{align\*?\}\s*(.*?)\\end\{align\*?\}\$\$',
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
        content, labels = _extract_math_labels(m.group(1).strip())
        block = f'$$\n{content}\n$$'
        if not labels:
            return block
        leading = convert_label_colons(labels[0])
        block = f'{block} ({leading})'
        extra = labels[1:]
        if extra:
            anchors = '\n'.join(f'({convert_label_colons(lbl)})=' for lbl in extra)
            return f'{anchors}\n{block}'
        return block

    text = re.sub(
        r'\$\$\\begin\{multline\*?\}\s*(.*?)\\end\{multline\*?\}\$\$',
        replace_math_block,
        text,
        flags=re.DOTALL
    )

    text = re.sub(
        r'\$\$\\begin\{gather\*?\}\s*(.*?)\\end\{gather\*?\}\$\$',
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
    begins with `>`.

    Pandoc preserves LaTeX source line wraps, so a snippet like

        ... we require that $r
        > 0$ and ...

    becomes two lines in markdown. MyST then parses the leading `>` as a
    blockquote marker, breaking both the math and the surrounding paragraph.
    Detect odd-parity unescaped `$` on a line followed by a line starting
    with `>` and merge them with a single space.

    Skips fenced code blocks (```) and display math blocks ($$) so genuine
    blockquotes are left alone.
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
            if next_stripped.startswith('>'):
                # The leading `>` is the math operator, not a blockquote.
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
