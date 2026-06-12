"""Environment-div transforms.

Converts pandoc's ``::: envname … :::`` fenced divs into MyST
directives. Default mapping in ``postprocess.ENV_MAP``; extended
per-project by ``apply_config`` from ``extra_environments`` /
``skip_environments`` in config.yaml.

Also decodes ``<!--DESCITEM-->`` markers emitted by the description
preprocess pass (lesson 022).

State coupling: ``ENV_MAP`` / ``ENV_SKIP`` (read at call time) and
per-file globals ``_last_exercise_label`` / ``_exercise_counter`` /
``_chapter_prefix`` (mutated by ``convert_environment_divs``, reset
by ``process_text``). All live on ``postprocess`` to keep the
mutation surface single-source-of-truth.
"""

from __future__ import annotations

import base64
import re

from conversion_context import current_context
from ._helpers import convert_label_colons, outer_fence


def convert_environment_divs(text: str, ctx=None) -> str:
    """Convert ::: envname ... ::: blocks to MyST directives.

    Handles:
    - ::: theorem ... ::: → ```{prf:theorem} ... ```
    - ::: Exercise ... ::: → ```{exercise} ... ```
    - ::: Answer ... ::: → ```{solution} ... ```
    - Nested labels []{#label label="label"} → :label: converted-label
    - *Proof.* markers inside proof blocks → removed (sphinx-proof adds its own)
    """
    ctx = ctx if ctx is not None else current_context()
    env_map = ctx.env_map
    env_skip = ctx.env_skip
    counters = ctx.counters

    lines = text.split('\n')
    result = []
    i = 0

    while i < len(lines):
        line = lines[i]

        # Match :::+ envname or :::+ {.envname} (3 or more colons)
        env_match = re.match(r'^:{3,} \{?\.?(\w+)\}?\s*$', line)

        # Match :::+ {#id} — generic div with just an id attribute
        id_div_match = re.match(r'^:{3,} \{#([^}\s]+)\}\s*$', line) if not env_match else None

        if id_div_match:
            div_id = convert_label_colons(id_div_match.group(1))
            # Emit a target label and keep the content
            result.append(f'({div_id})=')
            i += 1
            while i < len(lines) and not re.match(r'^:{3,}\s*$', lines[i]):
                result.append(lines[i])
                i += 1
            i += 1  # skip closing :::
            continue

        if env_match:
            env_name = env_match.group(1)

            if env_name in env_skip:
                # Skip the div wrapper, keep content (with nesting awareness)
                i += 1
                depth = 1
                while i < len(lines) and depth > 0:
                    if re.match(r'^:{3,}\s*$', lines[i]):
                        depth -= 1
                        if depth == 0:
                            i += 1
                            break
                        # Inner closing — skip it too
                    elif re.match(r'^:{3,} \w+', lines[i]):
                        depth += 1
                    else:
                        result.append(lines[i])
                    i += 1
                continue

            myst_env = env_map.get(env_name)
            if myst_env is None:
                # Unknown environment — keep as-is with a comment
                result.append(f'% Unknown environment: {env_name}')
                result.append(line)
                i += 1
                continue

            # Collect the body of the ::: block
            i += 1
            body_lines = []
            depth = 1
            while i < len(lines):
                if re.match(r'^:{3,}\s*$', lines[i]):
                    depth -= 1
                    if depth == 0:
                        i += 1
                        break
                elif re.match(r'^:{3,} \w+', lines[i]):
                    depth += 1
                body_lines.append(lines[i])
                i += 1

            # Extract the optional ``[title]`` preserved pre-pandoc by
            # ``_apply_prf_title_markers.py`` (issue #112). The marker
            # delimiters survive pandoc (escaped as ``\<!--…--\>``) while the
            # title text between them is pandoc-converted, so a ``\ref`` /
            # math in the title is already in pandoc-link form here — the
            # later ``convert_cross_references`` pass turns it into a role.
            #
            # The search is truncated at the first nested ``:::`` fence line:
            # THIS env's marker always lands at the start of its body (it was
            # injected on the first line after ``\begin{env}``), while a marker
            # past a nested fence belongs to an inner titled env — searching
            # the whole body would steal the inner env's title (caught in the
            # PR #115 detailed review). Any marker left in the body afterwards
            # (an inner env this single-level pass won't convert) is scrubbed
            # to its bold title text so the marker never leaks verbatim.
            prftitle_re = re.compile(
                r'\\?<!--PRFTITLE-START--\\?>(.*?)\\?<!--PRFTITLE-END--\\?>',
                re.DOTALL,
            )
            title_arg = None
            body_text = '\n'.join(body_lines)
            nested_cut = re.search(r'^\s*:{3,}', body_text, re.MULTILINE)
            region_end = nested_cut.start() if nested_cut else len(body_text)
            tm = prftitle_re.search(body_text, 0, region_end)
            if tm:
                title_arg = tm.group(1).strip()
                body_text = body_text[:tm.start()] + body_text[tm.end():]
            body_text = prftitle_re.sub(
                lambda m: f'**{m.group(1).strip()}**', body_text
            )
            body_lines = body_text.split('\n')

            # Extract label(s) from the body. Pandoc emits one or more
            # ``[]{#label label="label"}`` anchors anywhere on a line.
            # Multi-label LaTeX (e.g. ``\begin{Exercise}\label{a}\label{b}``)
            # produces adjacent / consecutive anchors. The first anchor
            # becomes ``:label:`` on the directive; subsequent anchors are
            # emitted as sibling ``{div}`` blocks above the directive (issue
            # #10) — each becomes its own valid cross-ref target.
            label = None
            extra_labels: list[str] = []
            clean_body = []
            anchor_re = re.compile(r'\[\]\{#([^\s}]+)(?:\s+label="[^"]*")?\}')
            for bline in body_lines:
                anchors = anchor_re.findall(bline)
                if anchors:
                    rest = anchor_re.sub('', bline)
                    if myst_env == 'prf:proof':
                        rest = re.sub(r'^\s*\*Proof\.\*\s*', '', rest)
                    rest = rest.strip()
                    for a in anchors:
                        a_conv = convert_label_colons(a)
                        if label is None:
                            label = a_conv
                        else:
                            extra_labels.append(a_conv)
                    if rest:
                        clean_body.append(rest)
                    continue
                # For proof blocks, remove a bare *Proof.* marker (sphinx-
                # proof adds its own opener).
                if myst_env == 'prf:proof' and re.match(r'^\*Proof\.\*\s*', bline):
                    rest = re.sub(r'^\*Proof\.\*\s*', '', bline).strip()
                    if rest:
                        clean_body.append(rest)
                    continue
                # Remove QED symbol
                if bline.strip() == '◻':
                    continue
                clean_body.append(bline)

            # Unwrap any skip-env divs (center / minipage / multicols)
            # NESTED in this body (#140). The body was collected verbatim,
            # so an inner ``::: center`` survives into the directive —
            # mystmd has no ``center`` directive and parses the colon fence
            # as a code block with ``lang: center``, rendering the content
            # as raw LaTeX. Walk with a fence stack: skip-env openers and
            # their matching closers are dropped (content kept, matching
            # the top-level skip branch); non-skip inner fences pass
            # through untouched.
            unwrapped: list[str] = []
            fence_kinds: list[str] = []  # 'skip' | 'keep'
            for bline in clean_body:
                open_m = re.match(r'^:{3,} \{?\.?(\w+)\}?\s*$', bline)
                if open_m:
                    kind = 'skip' if open_m.group(1) in env_skip else 'keep'
                    fence_kinds.append(kind)
                    if kind == 'skip':
                        continue
                elif re.match(r'^:{3,}\s*$', bline) and fence_kinds:
                    if fence_kinds.pop() == 'skip':
                        continue
                unwrapped.append(bline)
            clean_body = unwrapped

            # Strip leading/trailing blank lines from body
            while clean_body and clean_body[0].strip() == '':
                clean_body.pop(0)
            while clean_body and clean_body[-1].strip() == '':
                clean_body.pop()

            # A title carrying a cross-reference CANNOT go in the directive
            # argument: a role inside a prf directive argument poisons
            # mystmd's reference resolution for the whole page ("target was
            # not found" for unrelated same-page labels — verified against
            # myst v1.9.1 with a 12-line repro in the dp1 build test; the
            # plain-text control builds clean). At this point the title still
            # holds PANDOC ref syntax (``](#…){reference-type=…``) — detect
            # that and emit the title as a bold lead-in body line instead,
            # where the later cross-ref pass converts it and mystmd resolves
            # it fine. Plain titles (the common theorem-name case) keep the
            # argument form.
            title_in_body = bool(title_arg) and (
                '](#' in title_arg or '{reference-type=' in title_arg
            )
            if title_in_body:
                clean_body[:0] = [f'**{title_arg.rstrip(".")}.**', '']

            # Build the MyST directive. Size the fence to outrank any
            # code fence already in the body (issue #79 / lesson 040): a
            # ```python block inside an exercise/solution/proof would
            # otherwise close the directive early. Code blocks are emitted
            # by convert_pandoc_attr_code_blocks, which runs before this
            # pass, so they are present in clean_body here.
            fence = outer_fence('\n'.join(clean_body))
            header = f'{fence}{{{myst_env}}}'
            # Carry a plain preserved ``[title]`` as the directive argument
            # (``{prf:theorem} Neumann Series Lemma``). For a proof, the
            # explicit ``[Proof of …]`` becomes the heading and the inline
            # ``*Proof.*`` is stripped below, so the heading isn't doubled.
            if title_arg and not title_in_body:
                header = f'{header} {title_arg}'

            if myst_env == 'exercise':
                # Track exercise label for pairing with solution
                if not label:
                    # Auto-generate label for unlabeled exercises
                    counters.exercise_counter += 1
                    label = f'ex-{counters.chapter_prefix}-auto-{counters.exercise_counter}'
                counters.last_exercise_label = label
            elif myst_env == 'solution':
                # Solution needs the exercise label as argument
                if counters.last_exercise_label:
                    header = f'{fence}{{solution}} {counters.last_exercise_label}'
                counters.last_exercise_label = None

            # Emit any extra labels as sibling ``{div}`` anchor blocks
            # ahead of the directive. Multiple consecutive ``(label)=``
            # anchors all attach to the same next block and MyST keeps
            # only the last (warns "label X replaced with Y"); ``{div}``
            # directives each become their own anchor node — see issue
            # #10.
            for extra in extra_labels:
                result.append('```{div}')
                result.append(f':name: {extra}')
                result.append('```')
                result.append('')

            result.append(header)
            if myst_env == 'prf:proof':
                # LaTeX's proof environment is unnumbered by definition
                # (amsthm has no proof counter), so there is no input that
                # would warrant a numbered proof — but mystmd enumerates
                # bare {prf:proof} whenever the book turns on proof-family
                # numbering, producing "Proof 2.2.3" headers that clash
                # with the neighbouring theorem counters (#143). Emit
                # :nonumber: universally; precedent is #109's uncaptioned
                # algorithms. A :label: is still emitted when the source
                # carried one (harmless under :nonumber: — no number to
                # shift, the anchor still resolves).
                result.append(':nonumber:')
            if label and myst_env != 'solution':
                result.append(f':label: {label}')
            if clean_body:
                result.append('')
                result.extend(clean_body)
            result.append(fence)
            result.append('')
            continue

        result.append(line)
        i += 1

    return '\n'.join(result)


def convert_description_lists(text: str) -> str:
    """Decode ``<!--DESCRIPTION-START-->`` / ``<!--DESCITEM-->`` /
    ``<!--DESCRIPTION-END-->`` markers (emitted by
    ``_apply_description_markers.py``) into MyST definition-list syntax.

    Pandoc escapes the surrounding ``<`` / ``>`` to ``\\<`` / ``\\>`` on
    LaTeX→Markdown, so the regex tolerates both forms.

    A description block::

        <!--DESCRIPTION-START-->
        <!--DESCITEM term=BASE64TERM-->

        Item body, possibly multiple paragraphs.

        <!--DESCITEM term=BASE64TERM-->

        Second item body.

        <!--DESCRIPTION-END-->

    becomes::

        Term1
        : Item body, possibly multiple paragraphs.

        Term2
        : Second item body.

    Without this, pandoc emits ``::: description`` divs and silently
    drops every ``\\item[Term]`` label entirely — definitions arrive
    as a paragraph soup with no terms attached (GH #19).
    """
    block_pattern = re.compile(
        r'\\?<!--DESCRIPTION-START--\\?>(.*?)\\?<!--DESCRIPTION-END--\\?>',
        re.DOTALL,
    )
    item_pattern = re.compile(
        r'\\?<!--DESCITEM\s+term=(?P<term>[A-Za-z0-9+/=]*)--\\?>',
    )

    def render_block(m: re.Match) -> str:
        block = m.group(1)
        # Split on DESCITEM markers; we want (term_b64, body) pairs.
        positions = list(item_pattern.finditer(block))
        if not positions:
            return ''  # malformed — drop the empty wrapper
        rendered = []
        for idx, pos in enumerate(positions):
            term_b64 = pos.group('term')
            body_start = pos.end()
            body_end = positions[idx + 1].start() if idx + 1 < len(positions) else len(block)
            try:
                term = base64.b64decode(term_b64).decode('utf-8').strip()
            except Exception:
                term = ''
            body = block[body_start:body_end].strip()
            # MyST def-list: term on its own line, body indented under ``: ``.
            # Multi-paragraph bodies indent continuation lines so MyST
            # treats them as part of the same definition.
            if term and body:
                first, *rest = body.split('\n')
                lines = [term, f': {first}']
                for line in rest:
                    lines.append(f'  {line}' if line.strip() else line)
                rendered.append('\n'.join(lines))
            elif body:
                # No term — emit as a plain paragraph (matches LaTeX
                # behaviour of ``\item`` without ``[…]`` in description).
                rendered.append(body)
        return '\n\n'.join(rendered) + '\n'

    return block_pattern.sub(render_block, text)


# ── Exercise markers (#69) ───────────────────────────────────────────────────
#
# The companion ``scripts/_apply_enumerate_markers.py`` rewrites
# ``\begin{enumerate}`` blocks whose every ``\item`` carries
# ``\label{ex:...}`` into pairs of ``<!--EXERCISE-START -->`` /
# ``<!--EXERCISE-END-->`` markers, dissolving the list wrapper. Pandoc
# converts the item content to markdown and passes the markers
# through verbatim (escaping the angle brackets as ``\<`` / ``\>``).
# This resolver decodes each pair into a ``{exercise}`` MyST directive
# carrying the original label.

_EXERCISE_MARKER_RE = re.compile(
    r'\\?<!--EXERCISE-START\s+label=(?P<label>\S+)--\\?>'
    r'\s*(?P<content>.*?)\s*'
    r'\\?<!--EXERCISE-END--\\?>',
    re.DOTALL,
)


def resolve_exercise_markers(text: str) -> str:
    """Decode EXERCISE marker pairs into ``{exercise}`` directives.

    Marker format (from ``_apply_enumerate_markers.py``):

        <!--EXERCISE-START label=ex-ch1-1-->
        Markdown content (pandoc-converted item body)
        <!--EXERCISE-END-->

    becomes::

        ```{exercise}
        :label: ex-ch1-1

        Markdown content
        ```

    When the body itself contains a fenced code block the directive
    fence widens to outrank it (``outer_fence``), so a nested
    ```` ```python ```` block doesn't terminate the exercise early.

    Pandoc may escape ``<`` to ``\\<`` and ``>`` to ``\\>``; the regex
    tolerates both forms (mirrors ``resolve_listings``).
    """
    def repl(m: re.Match) -> str:
        label = m.group('label')
        content = (m.group('content') or '').strip()
        fence = outer_fence(content)
        return (
            f'{fence}{{exercise}}\n'
            f':label: {label}\n'
            '\n'
            f'{content}\n'
            f'{fence}'
        )

    return _EXERCISE_MARKER_RE.sub(repl, text)
