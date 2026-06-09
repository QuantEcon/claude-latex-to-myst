"""algorithm2e + algpseudocode body parsers (lesson 014 / 023).

algorithm2e blocks are intercepted before pandoc by
``_apply_algorithm_markers.py`` and base64-encoded inside HTML-comment
markers. Here we decode the markers and convert the algorithm2e
control commands (``\\While``, ``\\For``, ``\\KwIn`` etc.) into
nested bullet lists wrapped in ``{prf:algorithm}`` directives.

algpseudocode is a standalone parser path that doesn't go through
the marker mechanism — handled by ``resolve_algorithmics``.
"""

from __future__ import annotations

import base64
import re

from ._helpers import convert_label_colons, outer_fence


def _algo_find_balanced(s: str, start: int) -> int:
    """Given ``s[start] == '{'``, return the index of the matching ``}``
    (inclusive). Returns -1 if unbalanced.
    """
    if start >= len(s) or s[start] != '{':
        return -1
    depth = 0
    i = start
    while i < len(s):
        c = s[i]
        if c == '{':
            depth += 1
        elif c == '}':
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return -1


# algpseudocode (algorithmicx) keyword set. ``_algpseudo_convert_body`` is
# the native parser for this dialect — algorithm2e and algpseudocode use
# different shapes (paired \STATE/\FOR…\ENDFOR markers vs braced
# \While{}{} arguments) and translation between them is lossy
# (\REPEAT…\UNTIL{C} loses the condition, \LOOP has no algorithm2e
# equivalent, etc.) so each dialect gets its own walker. GH #20.
_ALGPSEUDO_KEYWORDS = (
    'STATE', 'STATEx', 'PRINT', 'COMMENT',
    'REQUIRE', 'ENSURE', 'INPUT', 'OUTPUT', 'RETURN',
    'FOR', 'FORALL', 'ENDFOR',
    'WHILE', 'ENDWHILE',
    'REPEAT', 'UNTIL',
    'IF', 'ELSIF', 'ELSE', 'ENDIF',
    'LOOP', 'ENDLOOP',
    'PROCEDURE', 'ENDPROCEDURE',
    'FUNCTION', 'ENDFUNCTION',
)
_ALGPSEUDO_KEYWORD_RE = re.compile(
    r'\\(' + '|'.join(_ALGPSEUDO_KEYWORDS) + r')(?![A-Za-z])'
)


def _unwrap_text_macro(text: str, macro: str, wrap: str) -> str:
    """Replace every ``\\<macro>{INNER}`` with ``wrap.format(inner)``,
    walking braces with balanced-depth matching so ``INNER`` containing
    nested ``{…}`` (typically math like ``\\mathcal{Q}`` or
    ``\\texttt{foo}``) is captured in full.

    The naive ``re.sub(r'\\\\<macro>\\{([^}]*)\\}', …)`` stops at the
    first ``}``, which for input like ``\\textbf{$\\mathcal{Q}$ is X}``
    yields ``**$\\mathcal{Q**$ is X}`` — markdown no parser agrees on
    (GH #21).
    """
    out: list[str] = []
    i = 0
    needle = '\\' + macro + '{'
    while True:
        j = text.find(needle, i)
        if j < 0:
            out.append(text[i:])
            return ''.join(out)
        brace_open = j + len(needle) - 1  # position of '{'
        brace_close = _algo_find_balanced(text, brace_open)
        if brace_close < 0:
            # Unbalanced — bail on this occurrence (preserve source) but
            # keep scanning past it so later occurrences still rewrite.
            out.append(text[i : j + len(needle)])
            i = j + len(needle)
            continue
        out.append(text[i:j])
        inner = text[brace_open + 1 : brace_close]
        out.append(wrap.format(inner))
        i = brace_close + 1


def _algpseudo_tokenize(body: str) -> list[dict]:
    """Split an algpseudocode body into an ordered list of token dicts.

    Each token is ``{'kw': str, 'arg': str | None, 'text': str}``:
      - ``kw``: the keyword (``STATE``, ``FOR``, ``ENDFOR``, …)
      - ``arg``: text inside the braced ``{…}`` argument if the keyword
        takes one (``FOR``, ``WHILE``, ``IF``, ``UNTIL``, ``ELSIF``,
        ``COMMENT``), else ``None``
      - ``text``: the prose body that follows the keyword (and arg) up
        to the next keyword, used for ``STATE``/``REQUIRE``/``ENSURE``
        /``RETURN``/``PRINT`` etc.

    Comments (``%…``), the ``\\algorithmiccomment`` annotation form, and
    bare formatting noise (``\\small``, ``\\footnotesize``, ``\\algrenewcommand``
    etc.) are stripped first.
    """
    # Strip line comments and size-change declarations that have no
    # structural meaning in the converted output.
    s = body
    # Drop full-line and trailing ``%`` comments (not inside math — but
    # algpseudocode bodies rarely have ``%`` mid-math, so this is safe).
    s = re.sub(r'(?<!\\)%.*$', '', s, flags=re.MULTILINE)
    for noise in ('small', 'footnotesize', 'scriptsize', 'normalsize',
                  'tiny', 'large', 'Large', 'algsetup', 'algrenewcommand'):
        s = re.sub(r'\\' + noise + r'\b', '', s)
    # ``\Comment{text}`` — algorithmicx in-line annotation. Reduce to
    # ``-- text`` so it can survive as a trailing comment on the
    # statement we're attaching it to. We just rewrite the source so
    # downstream walker doesn't need a special case.
    def _comment_to_inline(m):
        i = m.end() - 1  # position of '{'
        j = _algo_find_balanced(s, i)
        if j < 0:
            return m.group(0)
        inner = s[i + 1 : j]
        return f' (-- {inner.strip()})' + s[j + 1 : j + 1]  # ↓ rewritten below
    # Run the comment rewrite as a textual substitution so positions stay
    # consistent.
    out = []
    i = 0
    pat = re.compile(r'\\Comment\s*\{')
    while True:
        m = pat.search(s, i)
        if not m:
            out.append(s[i:])
            break
        out.append(s[i : m.start()])
        brace = m.end() - 1
        end = _algo_find_balanced(s, brace)
        if end < 0:
            out.append(s[m.start():])
            break
        inner = s[brace + 1 : end].strip()
        out.append(f' (-- {inner})')
        i = end + 1
    s = ''.join(out)

    tokens: list[dict] = []
    positions = list(_ALGPSEUDO_KEYWORD_RE.finditer(s))
    for idx, m in enumerate(positions):
        kw = m.group(1)
        # Some keywords take a braced ``{cond}`` argument immediately.
        arg: str | None = None
        cursor = m.end()
        if kw in {'FOR', 'FORALL', 'WHILE', 'IF', 'ELSIF', 'UNTIL',
                  'PROCEDURE', 'FUNCTION'}:
            # Skip whitespace, expect ``{``.
            j = cursor
            while j < len(s) and s[j] in ' \t\n':
                j += 1
            if j < len(s) and s[j] == '{':
                end = _algo_find_balanced(s, j)
                if end > 0:
                    arg = s[j + 1 : end]
                    cursor = end + 1
        # Prose body runs up to the next keyword (or end of source).
        text_end = positions[idx + 1].start() if idx + 1 < len(positions) else len(s)
        text = s[cursor:text_end]
        tokens.append({'kw': kw, 'arg': arg, 'text': text})
    return tokens


def _algpseudo_inline(text: str) -> str:
    """Clean up a single statement/condition for Markdown rendering.

    Drops algpseudocode-only macros that have no MyST analogue and
    collapses whitespace. Bold/text-style rewrites mirror those in
    ``_algo_convert_body`` so the two dialects render identically.
    """
    if text is None:
        return ''
    t = text
    # Balanced-brace unwrap — naive [^}]* stops at the first } and
    # mangles nested constructs like \textbf{$\mathcal{Q}$ X} (GH #21).
    t = _unwrap_text_macro(t, 'navy',        '**{}**')
    t = _unwrap_text_macro(t, 'textbf',      '**{}**')
    t = _unwrap_text_macro(t, 'textit',      '*{}*')
    t = _unwrap_text_macro(t, 'textnormal',  '{}')
    t = _unwrap_text_macro(t, 'emph',        '*{}*')
    # Inline macros that would otherwise leak verbatim (#106): ``\texttt`` →
    # code span, ``\eqref`` → ``{eq}`` role (the algorithm body never reaches
    # the prose-side cross-ref / code passes).
    t = _unwrap_text_macro(t, 'texttt',      '`{}`')
    t = re.sub(
        r'\\eqref\{([^}]+)\}',
        lambda m: '{eq}`' + convert_label_colons(m.group(1)) + '`',
        t,
    )
    # Strip leftover algpseudocode formatting that doesn't apply here.
    t = re.sub(r'\\vspace\{[^}]*\}', '', t)
    # Collapse whitespace — algpseudocode tolerates arbitrary linebreaks
    # inside a STATE body, but Markdown bullet items want a single line.
    t = re.sub(r'\s+', ' ', t).strip()
    return t


def _algpseudo_convert_body(body: str) -> str:
    """Convert an algpseudocode (algorithmicx) body to a Markdown bullet
    list. Native parser for paired-marker syntax — see
    ``_ALGPSEUDO_KEYWORDS``. Used both for standalone ``algorithmic``
    blocks (decoded from ``<!--ALGORITHMIC body=…-->`` markers) and for
    ``\\begin{algorithmic}`` bodies nested inside ``\\begin{algorithm}``
    wrappers (the algorithm2e converter delegates here when it sees
    algpseudocode keywords).

    The parser maintains a stack of open blocks and emits Markdown
    bullets with indentation that matches block depth. Closing
    keywords (``\\ENDFOR``, ``\\ENDWHILE``, ``\\UNTIL{C}``, ``\\ENDIF``,
    etc.) pop the stack; ``\\ELSE`` / ``\\ELSIF`` open a sibling branch
    at the same depth.
    """
    # Strip the ``\begin{algorithmic}…\end{algorithmic}`` wrapper if
    # present (the standalone preprocessor strips this, but when called
    # from the algorithm path the wrapper is still there).
    body = re.sub(
        r'\\begin\{algorithmic\}(?:\[[^\]]*\])?',
        '',
        body,
    )
    body = body.replace('\\end{algorithmic}', '')

    tokens = _algpseudo_tokenize(body)

    lines: list[str] = []
    depth = 0  # current nesting level (bullet indent = 2 * depth)
    stack: list[str] = []  # open block keywords (FOR, WHILE, IF, REPEAT, LOOP, …)

    def emit(content: str) -> None:
        if not content:
            return
        lines.append('  ' * depth + '- ' + content)

    def emit_header(content: str) -> None:
        """Open a new block: emit the header bullet and bump depth."""
        nonlocal depth
        emit(content)
        depth += 1

    def close_block(expected_open: set[str]) -> None:
        nonlocal depth
        while stack and stack[-1] not in expected_open:
            # Tolerate slightly mis-nested input by popping until we
            # find the matching opener; safer than asserting.
            stack.pop()
            if depth > 0:
                depth -= 1
        if stack:
            stack.pop()
            if depth > 0:
                depth -= 1

    for tok in tokens:
        kw = tok['kw']
        arg = _algpseudo_inline(tok['arg']) if tok['arg'] is not None else None
        text = _algpseudo_inline(tok['text'])

        if kw in ('STATE', 'STATEx', 'PRINT'):
            emit(text)
        elif kw == 'REQUIRE' or kw == 'INPUT':
            emit(f'**Input:** {text}' if text else '**Input:**')
        elif kw == 'ENSURE' or kw == 'OUTPUT':
            emit(f'**Output:** {text}' if text else '**Output:**')
        elif kw == 'RETURN':
            emit(f'return {text}' if text else 'return')
        elif kw == 'COMMENT':
            # Standalone \COMMENT{...} — rare; if seen at top level emit
            # as italicized note rather than a bullet so it stands out.
            if arg:
                emit(f'*{arg}*')
        elif kw == 'FOR':
            stack.append('FOR')
            emit_header(f'for {arg} do' if arg else 'for do')
            if text:
                emit(text)
        elif kw == 'FORALL':
            stack.append('FOR')  # closed by same \ENDFOR
            emit_header(f'for all {arg} do' if arg else 'for all do')
            if text:
                emit(text)
        elif kw == 'ENDFOR':
            close_block({'FOR'})
            emit('end')   # algorithm2e-style loop terminator (#109)
            if text:
                emit(text)
        elif kw == 'WHILE':
            stack.append('WHILE')
            emit_header(f'while {arg} do' if arg else 'while do')
            if text:
                emit(text)
        elif kw == 'ENDWHILE':
            close_block({'WHILE'})
            emit('end')   # algorithm2e-style loop terminator (#109)
            if text:
                emit(text)
        elif kw == 'REPEAT':
            stack.append('REPEAT')
            emit_header('repeat:')
            if text:
                emit(text)
        elif kw == 'UNTIL':
            # Closes the matching REPEAT and emits a trailing "until C"
            # bullet at the now-restored depth so the condition is
            # preserved (unlike algorithm2e's one-arg \Repeat).
            close_block({'REPEAT'})
            emit(f'until {arg}' if arg else 'until')
            if text:
                emit(text)
        elif kw == 'IF':
            stack.append('IF')
            emit_header(f'if {arg}:' if arg else 'if:')
            if text:
                emit(text)
        elif kw == 'ELSIF':
            # Pop the previous IF/ELSIF branch (drop depth), open a new
            # sibling at the same depth.
            if stack and stack[-1] in ('IF', 'ELSIF', 'ELSE'):
                stack.pop()
                if depth > 0:
                    depth -= 1
            stack.append('ELSIF')
            emit_header(f'else if {arg}:' if arg else 'else if:')
            if text:
                emit(text)
        elif kw == 'ELSE':
            if stack and stack[-1] in ('IF', 'ELSIF'):
                stack.pop()
                if depth > 0:
                    depth -= 1
            stack.append('ELSE')
            emit_header('else:')
            if text:
                emit(text)
        elif kw == 'ENDIF':
            close_block({'IF', 'ELSIF', 'ELSE'})
            if text:
                emit(text)
        elif kw == 'LOOP':
            stack.append('LOOP')
            emit_header('loop:')
            if text:
                emit(text)
        elif kw == 'ENDLOOP':
            close_block({'LOOP'})
            if text:
                emit(text)
        elif kw in ('PROCEDURE', 'FUNCTION'):
            stack.append(kw)
            label = 'procedure' if kw == 'PROCEDURE' else 'function'
            emit_header(f'{label} {arg}:' if arg else f'{label}:')
            if text:
                emit(text)
        elif kw in ('ENDPROCEDURE', 'ENDFUNCTION'):
            close_block({'PROCEDURE', 'FUNCTION'})
            if text:
                emit(text)

    return '\n'.join(lines).strip()


def _algo_convert_body(body: str) -> str:
    """Convert an algorithm2e body to a Markdown bullet list.

    Recognises:
      - ``\\DontPrintSemicolon``, ``\\SetAlgoLined``, ``\\vspace{..}``,
        ``\\index{..}`` : dropped
      - ``\\;`` : statement terminator (bullet boundary)
      - ``\\While{C}{B}``, ``\\For{C}{B}``, ``\\ForEach{C}{B}`` : control block
      - ``\\If{C}{B}``, ``\\uIf{C}{B}``, ``\\ElseIf{C}{B}`` : conditional block
      - ``\\lIf{C}{B}`` : single-line conditional (no nested bullets)
      - ``\\Repeat{B}`` : one-arg control block (header "repeat:")
      - ``\\Return{X}``, ``\\KwResult{X}``, ``\\KwIn{X}``, ``\\KwOut{X}`` :
        one-arg statement
      - ``\\navy{x}``, ``\\textbf{x}`` : bold

    Statements are emitted as bullet items; nested blocks are indented under
    their header. The parser is recursive so deeply-nested ``\\While``/``\\If``
    structures expand correctly.

    Dispatches to ``_algpseudo_convert_body`` when the body contains
    algpseudocode (algorithmicx) keywords — this lets a single
    ``\\begin{algorithm}\\begin{algorithmic}…\\end{algorithmic}\\end{algorithm}``
    block render correctly whether the inner pseudocode uses algorithm2e
    or algorithmicx syntax. GH #20.
    """
    if _ALGPSEUDO_KEYWORD_RE.search(body) or '\\begin{algorithmic}' in body:
        return _algpseudo_convert_body(body)

    s = body

    # Source-LaTeX indentation is incidental; only the structural indentation
    # produced by recursive expansion below should survive into the output.
    s = '\n'.join(line.lstrip(' \t') for line in s.split('\n'))

    # Drop noise commands.
    s = re.sub(r'\\DontPrintSemicolon', '', s)
    s = re.sub(r'\\SetAlgoLined', '', s)
    s = re.sub(r'\\vspace\{[^}]*\}', '', s)
    s = re.sub(r'\\index\{[^}]*\}', '', s)
    # algorithm2e inline comments: ``\tcp{c}`` / ``\tcp*{c}`` (and the
    # ``\tcc`` block form) → ``(-- c)`` so the note survives instead of
    # leaking as literal ``\tcp{...}`` (#109). ``*`` form first (the
    # ``\tcp{`` needle wouldn't match ``\tcp*{``).
    s = _unwrap_text_macro(s, 'tcp*', '(-- {})')
    s = _unwrap_text_macro(s, 'tcp',  '(-- {})')
    s = _unwrap_text_macro(s, 'tcc*', '(-- {})')
    s = _unwrap_text_macro(s, 'tcc',  '(-- {})')
    # Drop ``%`` line comments the algorithm2e body may carry (mirrors the
    # algpseudocode tokenizer) so they don't leak as ``% ...`` bullets (#109).
    s = re.sub(r'(?<!\\)%.*$', '', s, flags=re.MULTILINE)
    # Balanced-brace unwrap — naive [^}]* stops at the first } and
    # mangles nested math like \textbf{$\mathcal{Q}$ X} (GH #21).
    s = _unwrap_text_macro(s, 'navy',   '**{}**')
    s = _unwrap_text_macro(s, 'textbf', '**{}**')
    # ``\textnormal{...}`` is LaTeX's way to drop into upright text inside
    # math mode; in an algorithm condition like ``\While{\textnormal{true}}``
    # the wrapper has no markdown equivalent — unwrap it. (FOLLOWUP #014, Gap B)
    s = _unwrap_text_macro(s, 'textnormal', '{}')
    # Inline macros that otherwise leak verbatim inside an algorithm body
    # (the body is base64'd pre-pandoc, so the prose-side cross-ref / code
    # passes never see it — #106). ``\texttt{x}`` → code span;
    # ``\eqref{eq:x}`` → ``{eq}`eq-x``` (``{eq}`` is unambiguous, no routing
    # table needed).
    s = _unwrap_text_macro(s, 'texttt', '`{}`')
    s = re.sub(
        r'\\eqref\{([^}]+)\}',
        lambda m: '{eq}`' + convert_label_colons(m.group(1)) + '`',
        s,
    )

    # Repeatedly expand control blocks (innermost first via simple loop).
    def expand_one(text: str) -> tuple[str, bool]:
        # Two-arg control blocks. ``closer`` is the algorithm2e block
        # terminator (#109): loops render ``while C do … end`` /
        # ``for … do … end``; conditionals keep the ``if C:`` colon form.
        for cmd, header_fmt, closer in (
            ('While',   'while {} do',     'end'),
            ('For',     'for {} do',       'end'),
            ('ForEach', 'for each {} do',  'end'),
            ('If',      'if {}:',          None),
            ('uIf',     'if {}:',          None),
            ('ElseIf',  'else if {}:',     None),
            ('lIf',     'if {}: {}',       None),
        ):
            pat = re.compile(r'\\' + cmd + r'\s*\{')
            m = pat.search(text)
            if not m:
                continue
            i = m.end() - 1  # position of '{'
            j = _algo_find_balanced(text, i)
            if j < 0:
                continue
            cond = text[i + 1 : j]
            # Find next '{' for body.
            k = j + 1
            while k < len(text) and text[k] in ' \t\n':
                k += 1
            if k >= len(text) or text[k] != '{':
                continue
            l = _algo_find_balanced(text, k)
            if l < 0:
                continue
            body_inner = text[k + 1 : l]
            cond = cond.strip()
            body_inner = _algo_convert_body(body_inner).strip()
            if cmd == 'lIf':
                # Single-line if: "if cond: body" (no nested bullets).
                inner_flat = re.sub(r'\s+', ' ', body_inner.lstrip('-').strip())
                replacement = f'\\NEWLINE\\if {cond}: {inner_flat}\\NEWLINE\\'
            else:
                indented = '\n'.join('  ' + ln for ln in body_inner.split('\n'))
                replacement = (
                    f'\\NEWLINE\\{header_fmt.format(cond)}\\NEWLINE\\'
                    f'{indented}\\NEWLINE\\'
                )
                if closer:
                    replacement += f'{closer}\\NEWLINE\\'
            return text[: m.start()] + replacement + text[l + 1 :], True

        # \Repeat{body}: one-arg control block.
        m = re.search(r'\\Repeat\s*\{', text)
        if m:
            i = m.end() - 1
            j = _algo_find_balanced(text, i)
            if j > 0:
                body_inner = text[i + 1 : j]
                body_inner = _algo_convert_body(body_inner).strip()
                indented = '\n'.join('  ' + ln for ln in body_inner.split('\n'))
                replacement = (
                    f'\\NEWLINE\\repeat:\\NEWLINE\\{indented}\\NEWLINE\\'
                )
                return text[: m.start()] + replacement + text[j + 1 :], True

        # One-arg statement commands.
        one_arg_cmds = (
            ('Return',   'return {}'),
            ('KwResult', 'result: {}'),
            ('KwIn',     'input: {}'),
            ('KwOut',    'output: {}'),
        )
        for cmd, fmt in one_arg_cmds:
            pat = re.compile(r'\\' + cmd + r'\s*\{')
            m = pat.search(text)
            if not m:
                continue
            i = m.end() - 1
            j = _algo_find_balanced(text, i)
            if j < 0:
                continue
            arg = text[i + 1 : j].strip()
            # Bracket with ``\NEWLINE\`` so the command is its own line: these
            # algorithm2e macros (\KwIn, \KwOut, \Return, …) don't carry a
            # ``\;`` terminator, so without an explicit boundary the soft-wrap
            # join would fuse them into the neighbouring statement (#109).
            replacement = f'\\NEWLINE\\{fmt.format(arg)}\\NEWLINE\\'
            return text[: m.start()] + replacement + text[j + 1 :], True

        # Unbraced one-arg fallback — covers ``\Return $\theta$`` and
        # similar where the author skipped the braces. Stops at ``\;`` or
        # end of line. (FOLLOWUP #014, Gap C.) ``(?![A-Za-z])`` prevents
        # matching e.g. ``\Returnix`` as ``\Return``.
        for cmd, fmt in one_arg_cmds:
            pat = re.compile(
                r'\\' + cmd + r'(?![A-Za-z])\s+([^\n]+?)\s*(?=\\;|\n|$)'
            )
            m = pat.search(text)
            if not m:
                continue
            arg = m.group(1).strip()
            replacement = f'\\NEWLINE\\{fmt.format(arg)}\\NEWLINE\\'
            return text[: m.start()] + replacement + text[m.end() :], True

        return text, False

    changed = True
    while changed:
        s, changed = expand_one(s)

    # Split on statement terminators (``\;``) and ``\NEWLINE\`` placeholders
    # to produce bullet items. Indent from recursive expansion is preserved.
    s = s.replace('\\;', '\\NEWLINE\\')
    parts = re.split(r'\\NEWLINE\\', s)
    out_lines: list[str] = []
    for p in parts:
        block_lines = p.split('\n')
        # A part is either an already-formatted recursion block (its lines
        # start with ``- `` / ``  - ``) or a single plain statement. A plain
        # statement that soft-wrapped across source lines (no ``\;`` between
        # them) must stay ONE bullet — splitting on ``\n`` here is what cut
        # "…that\ndepends…" into two steps (#109). Only iterate per-line when
        # the part actually carries bullet markers.
        if any(ln.lstrip().startswith('- ') for ln in block_lines):
            for line in block_lines:
                stripped = line.lstrip(' ')
                indent = len(line) - len(stripped)
                content = re.sub(r'\s+', ' ', stripped).strip()
                if not content:
                    continue
                pad = ' ' * indent
                if content.startswith('- '):
                    out_lines.append(f'{pad}{content}')
                else:
                    out_lines.append(f'{pad}- {content}')
        else:
            content = re.sub(r'\s+', ' ', p).strip()
            if content:
                out_lines.append(f'- {content}')

    return '\n'.join(out_lines).strip()


# convert_pandoc_attr_code_blocks moved to transforms/code.py (P3a)

# convert_description_lists moved to transforms/envs.py (P3a)

def resolve_algorithms(text: str) -> str:
    """Replace ALGORITHM markers with ``{prf:algorithm}`` directives.

    Marker format (emitted by _apply_algorithm_markers.py):
        <!--ALGORITHM name=NAME numbered=0|1 title=TITLE body=BASE64-->

    The body is base64-encoded so pandoc passes it through verbatim
    (otherwise pandoc would strip ``\\;`` and reformat ``\\While`` etc.).
    Pandoc may escape ``<`` to ``\\<``; the regex tolerates both forms.

    ``numbered=0`` (an uncaptioned algorithm2e float) emits ``:nonumber:`` so
    it doesn't take a number or shift the captioned algorithms' counter (#109).
    """
    pattern = re.compile(
        r'\\?<!--ALGORITHM\s+'
        r'name=(?P<name>\S+)\s+'
        r'numbered=(?P<numbered>[01])\s+'
        r'title=(?P<title>.*?)\s+'
        r'body=(?P<body>[A-Za-z0-9+/=]+)--\\?>',
        re.DOTALL,
    )

    def repl(m: re.Match) -> str:
        name = m.group('name').strip()
        numbered = m.group('numbered') == '1'
        title = (m.group('title') or '').strip()
        body_b64 = m.group('body').strip()
        try:
            body = base64.b64decode(body_b64).decode('utf-8')
        except Exception:
            body = ''
        converted = _algo_convert_body(body)
        # Size the fence to outrank any code fence in the body (issue #79
        # / lesson 040); normally a no-op for pseudocode, but defensive
        # against an algorithm body that embeds a fenced block.
        fence = outer_fence(converted)
        out = []
        if title:
            out.append(f'{fence}{{prf:algorithm}} {title}')
        else:
            out.append(f'{fence}{{prf:algorithm}}')
        if not numbered:
            out.append(':nonumber:')
        if name and name != 'NOLABEL':
            out.append(f':label: {name}')
        out.append('')
        out.append(converted)
        out.append(fence)
        return '\n'.join(out)

    return pattern.sub(repl, text)


def resolve_algorithmics(text: str) -> str:
    """Replace standalone ALGORITHMIC markers with a Markdown bullet list.

    Marker format (emitted by ``_apply_algorithmic_markers.py``)::

        <!--ALGORITHMIC body=BASE64-->

    Unlike ``resolve_algorithms`` (the algorithm2e-wrapping variant),
    there is no ``{prf:algorithm}`` directive wrapper — the source had
    no caption or label, so the body renders as bare bullets that fit
    inside whatever wrapper the author chose (custom tcolorbox,
    ``definitionbox`` div, or plain prose). Pandoc may escape ``<`` to
    ``\\<``; the regex tolerates both forms (GH #20).
    """
    pattern = re.compile(
        r'\\?<!--ALGORITHMIC\s+body=(?P<body>[A-Za-z0-9+/=]+)--\\?>',
        re.DOTALL,
    )

    def repl(m: re.Match) -> str:
        body_b64 = m.group('body').strip()
        try:
            body = base64.b64decode(body_b64).decode('utf-8')
        except Exception:
            return ''
        return _algpseudo_convert_body(body)

    return pattern.sub(repl, text)


