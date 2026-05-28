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

from ._helpers import convert_label_colons, outer_fence


def convert_environment_divs(text: str) -> str:
    """Convert ::: envname ... ::: blocks to MyST directives.

    Handles:
    - ::: theorem ... ::: → ```{prf:theorem} ... ```
    - ::: Exercise ... ::: → ```{exercise} ... ```
    - ::: Answer ... ::: → ```{solution} ... ```
    - Nested labels []{#label label="label"} → :label: converted-label
    - *Proof.* markers inside proof blocks → removed (sphinx-proof adds its own)
    """
    import postprocess as pp
    env_map = pp.ENV_MAP
    env_skip = pp.ENV_SKIP

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

            # Strip leading/trailing blank lines from body
            while clean_body and clean_body[0].strip() == '':
                clean_body.pop(0)
            while clean_body and clean_body[-1].strip() == '':
                clean_body.pop()

            # Build the MyST directive. Size the fence to outrank any
            # code fence already in the body (issue #79 / lesson 040): a
            # ```python block inside an exercise/solution/proof would
            # otherwise close the directive early. Code blocks are emitted
            # by convert_pandoc_attr_code_blocks, which runs before this
            # pass, so they are present in clean_body here.
            fence = outer_fence('\n'.join(clean_body))
            header = f'{fence}{{{myst_env}}}'

            if myst_env == 'exercise':
                # Track exercise label for pairing with solution
                if not label:
                    # Auto-generate label for unlabeled exercises
                    pp._exercise_counter += 1
                    label = f'ex-{pp._chapter_prefix}-auto-{pp._exercise_counter}'
                pp._last_exercise_label = label
            elif myst_env == 'solution':
                # Solution needs the exercise label as argument
                if pp._last_exercise_label:
                    header = f'{fence}{{solution}} {pp._last_exercise_label}'
                pp._last_exercise_label = None

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
