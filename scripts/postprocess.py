#!/usr/bin/env python3
"""Post-process pandoc markdown output into MyST Markdown.

Transforms pandoc's markdown syntax into proper MyST Markdown:
- ::: envname ... ::: → ```{prf:envname} ... ```
- pandoc cross-refs → MyST {ref}, {eq}, {prf:ref}, {numref}
- pandoc citations → MyST {cite} / {cite:t}
- $$\\begin{equation}...\\end{equation}$$ → $$ ... $$ (label)
- ![cap](path){attrs} → ```{figure} ... ```
- labels: colons → hyphens

This is the generic transform library from claude-latex-to-myst. Project-specific
data (chapter titles, TikZ resolution maps) is loaded from a YAML config and an
optional Python overrides file — never hard-coded here.

Usage:
    postprocess.py --config path/to/config.yaml [INPUT_FILE ...]

If INPUT_FILE args are given, only those files are processed. Otherwise every
chapter listed in the config is processed.
"""

import argparse
import base64
import importlib.util
import re
import sys
from pathlib import Path

# ── Environment mapping ──────────────────────────────────────────────────────

# Default mapping from pandoc-emitted ``::: envname`` divs to MyST directive
# names. Extended per-project via ``config.extra_environments`` / consumed
# (skip-only) via ``config.skip_environments``. Both lists are merged into
# the module-level dicts by ``apply_config`` — never edit per-book entries
# in this file.
ENV_MAP = {
    # sphinx-proof environments
    'theorem':        'prf:theorem',
    'boxtheorem':     'prf:theorem',
    'lemma':          'prf:lemma',
    'proof':          'prf:proof',
    'definition':     'prf:definition',
    'boxdefinition':  'prf:definition',
    'proposition':    'prf:proposition',
    'boxproposition': 'prf:proposition',
    'corollary':      'prf:corollary',
    'boxcorollary':   'prf:corollary',
    'example':        'prf:example',
    'remark':         'prf:remark',
    'assumption':     'prf:assumption',
    'algorithm':      'prf:algorithm',
    # MyST exercise directive
    'Exercise':       'exercise',
    'Answer':         'solution',
}

# Track the last exercise label so we can associate solutions
_last_exercise_label = None

# Counter for auto-generated exercise labels (reset per file)
_exercise_counter = 0

# Chapter prefix for auto-generated labels (set per file)
_chapter_prefix = ''

# Environments to skip (remove the div wrapper, keep content)
ENV_SKIP = {'multicols', 'minipage', 'center'}

# Prose nouns that get doubled by writers in front of a {prf:ref}. Sphinx-proof
# auto-renders the noun (e.g. "Theorem 1.2"), so leaving the prose noun produces
# "Theorem Theorem 1.2" in the output. The second column is the label prefix
# that confirms the ref points to that kind of object — guards against stripping
# "Theorem ..." in front of a ref to something unrelated.
#
# Plural forms are listed alongside singulars so prose like
# ``Chapters {prf:ref}`c-X` and {prf:ref}`c-Y```` (sphinx-proof renders
# each ref as "Chapter N") also gets de-doubled. Multi-target shapes
# (range/list separators) don't need extra handling: only the leading
# plural-noun token is redundant; the refs between separators have no
# intervening noun for sphinx-proof to collide with.
# _DOUBLED_NOUN_REFS moved to transforms/refs.py (P3a)

from transforms._helpers import convert_label_colons  # re-export (P3a)


def convert_environment_divs(text: str) -> str:
    """Convert ::: envname ... ::: blocks to MyST directives.
    
    Handles:
    - ::: theorem ... ::: → ```{prf:theorem} ... ```
    - ::: Exercise ... ::: → ```{exercise} ... ```
    - ::: Answer ... ::: → ```{solution} ... ```
    - Nested labels []{#label label="label"} → :label: converted-label
    - *Proof.* markers inside proof blocks → removed (sphinx-proof adds its own)
    """
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
            
            if env_name in ENV_SKIP:
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
            
            myst_env = ENV_MAP.get(env_name)
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
            #
            # The regex captures the marker anywhere on the line; ``sub('', …)``
            # strips it and leaves the surrounding whitespace in place. For
            # ``\begin{proof}[Proof of …]\label{p:foo}`` the leading
            # ``*Proof of …*`` opener stays intact (sphinx-proof renders just
            # the prefix). For the bare ``\begin{proof}\label{p:foo}`` case,
            # the residual ``*Proof.*`` is also stripped — sphinx-proof
            # renders its own opener (issue #4).
            label = None
            extra_labels: list[str] = []
            title = None
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
            
            # Build the MyST directive
            header = f'```{{{myst_env}}}'
            
            global _last_exercise_label, _exercise_counter
            
            if myst_env == 'exercise':
                # Track exercise label for pairing with solution
                if not label:
                    # Auto-generate label for unlabeled exercises
                    _exercise_counter += 1
                    label = f'ex-{_chapter_prefix}-auto-{_exercise_counter}'
                _last_exercise_label = label
            elif myst_env == 'solution':
                # Solution needs the exercise label as argument
                if _last_exercise_label:
                    header = f'```{{solution}} {_last_exercise_label}'
                _last_exercise_label = None
            
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
            result.append('```')
            result.append('')
            continue
        
        result.append(line)
        i += 1
    
    return '\n'.join(result)


from transforms.typography import (  # noqa: E402  (re-exports for P3a)
    strip_pandoc_html_separators,
    convert_epigraphs,
    cleanup_typography,
    compress_directive_whitespace,
)
from transforms.math import (  # noqa: E402  (re-exports for P3a)
    fix_text_dollar,
    convert_equations,
    join_split_inline_math,
    strip_blank_lines_in_math,
    ensure_blank_after_display_math,
)
from transforms.cite import (  # noqa: E402  (re-exports for P3a)
    decode_natbib_markers,
    convert_citations,
)
from transforms.refs import (  # noqa: E402  (re-exports for P3a)
    convert_cross_references,
    strip_doubled_noun_refs,
    strip_doubled_section_symbol,
    strip_footnote_refs,
)
from transforms.tables import convert_simple_tables  # noqa: E402  (P3a)

# _DEFAULT_CROSS_REF_ROUTING moved to transforms/refs.py (P3a)

# Per-book extension of the routing table. Populated by ``apply_config``
# from ``cross_ref_routing`` in config.yaml. Extras take precedence over
# defaults so a book can override the role for a prefix the defaults
# already match.
_EXTRA_CROSS_REF_ROUTING: list[tuple[tuple[str, ...], str]] = []


# convert_cross_references moved to transforms/refs.py (P3a)

# _NATBIB_MARKER_ROLE moved to transforms/cite.py (P3a)



# decode_natbib_markers moved to transforms/cite.py (P3a)

# convert_citations moved to transforms/cite.py (P3a)

def convert_figures(text: str) -> str:
    """Convert pandoc image syntax to MyST figure directives.
    
    ![caption []{#label}](path){#id width="X%"} →
    ```{figure} figures/path
    :name: label
    :width: X%
    caption
    ```
    """
    def replace_figure(m):
        full_match = m.group(0)
        caption = m.group(1)
        path = m.group(2)
        attrs = m.group(3) if m.group(3) else ''
        
        # Extract label from caption: []{#label label="label"}
        label = None
        label_match = re.search(r'\[\]\{#([^\s}]+)(?:\s+label="[^"]*")?\}', caption)
        if label_match:
            label = convert_label_colons(label_match.group(1))
            caption = re.sub(r'\[\]\{#[^}]+\}\s*', '', caption).strip()
        
        # Extract label from attrs: {#id ...}
        if not label:
            id_match = re.search(r'#([^\s}]+)', attrs)
            if id_match:
                label = convert_label_colons(id_match.group(1))
        
        # Extract width from attrs
        width = None
        width_match = re.search(r'width="?([^"\s}]+)"?', attrs)
        if width_match:
            width = width_match.group(1)
        
        # Ensure path starts with figures/
        if not path.startswith('figures/'):
            path = 'figures/' + path
        
        lines = [f'```{{figure}} {path}']
        if label:
            lines.append(f':name: {label}')
        if width:
            lines.append(f':width: {width}')
        lines.append('')
        if caption:
            lines.append(caption)
        lines.append('```')
        
        return '\n'.join(lines)
    
    # Match ![caption](path){attrs} or ![caption](path)
    # Caption may contain nested brackets like []{#label label="label"}
    text = re.sub(
        r'!\[((?:[^\[\]]|\[[^\]]*\])*)\]\(([^)]+)\)(?:\{([^}]*)\})?',
        replace_figure,
        text
    )
    
    return text


def convert_section_labels(text: str) -> str:
    """Convert pandoc section header IDs to MyST label syntax.

    # Title {#sec:label} → (sec-label)=\\n# Title

    Pandoc may append class/property tokens after the slug for unnumbered
    or unlisted headings (``{#slug .unnumbered .unlisted}``); these are
    HTML class attributes and must be stripped before forming the MyST
    label. Only the first whitespace-delimited token (the ``#slug``) is
    treated as the identifier.
    """
    def replace_header(m):
        hashes = m.group(1)
        title = m.group(2).strip()
        slug = m.group(3).split()[0]
        label = convert_label_colons(slug)
        return f'({label})=\n{hashes} {title}'
    
    text = re.sub(
        r'^(#{1,6})\s+(.+?)\s+\{#([^}]+)\}\s*$',
        replace_header,
        text,
        flags=re.MULTILINE
    )
    
    return text


def convert_standalone_labels(text: str) -> str:
    """Convert standalone []{#label ...} to MyST target syntax.

    Own-line ``[]{#label label="label"}`` → ``(label)=``.

    Mid-line orphan anchors that survived all previous transforms (typically
    inside a markdown footnote body produced from
    ``\\footnote{\\label{fn:foo}…}``, or any other context the env-div
    promoter doesn't reach) are stripped. MyST footnotes are addressed via
    the markdown ``[^N]`` syntax — a ``\\label{}`` on a footnote has no
    MyST destination, so dropping the artifact is correct (issue #10). If
    a future case needs the anchor preserved we can add a more targeted
    promotion path then.
    """
    # Own-line anchor → MyST cross-ref target
    text = re.sub(
        r'^\[\]\{#([^\s}]+)(?:\s+label="[^"]*")?\}\s*$',
        lambda m: f'({convert_label_colons(m.group(1))})=',
        text,
        flags=re.MULTILINE,
    )
    # Strip residual mid-line orphan anchors (the own-line ones are gone
    # after the first sub; only mid-line survivors remain).
    text = re.sub(
        r'\[\]\{#[^\s}]+(?:\s+label="[^"]*")?\}',
        '',
        text,
    )
    return text


# convert_simple_tables moved to transforms/tables.py (P3a)

# convert_epigraphs moved to transforms/typography.py (P3a)


def convert_html_figures(text: str) -> str:
    """Convert HTML figure blocks (from TikZ placeholders) to MyST admonitions.

    <figure id="..."> ... <figcaption>...</figcaption> </figure>
    → ```{figure} #placeholder
      :name: ...
      Caption text (TikZ diagram — needs manual conversion)
      ```

    Also handles the nested subfigure pattern that pandoc emits for
    ``\\begin{subfigure}`` environments:

        <figure id="parent">
          <figure id="child_a"> ... <figcaption>cap_a</figcaption> </figure>
          <figure id="child_b"> ... <figcaption>cap_b</figcaption> </figure>
          <figcaption>parent_caption</figcaption>
        </figure>

    For nested patterns the parent label becomes a section anchor and each
    labelled subfigure becomes its own admonition placeholder.
    """
    def make_admonition(label, caption):
        lines = ['```{admonition} Figure (TikZ — needs manual conversion)']
        if label:
            lines.append(f':name: {label}')
        lines.append('')
        lines.append(caption or '*(TikZ diagram — needs manual conversion)*')
        lines.append('```')
        return '\n'.join(lines)

    def extract_caption(block):
        cap_match = re.search(
            r'<figcaption>(?:<[^>]*>)*\s*(.*?)\s*</figcaption>',
            block,
            re.DOTALL,
        )
        if not cap_match:
            return ''
        cap = cap_match.group(1)
        # Convert pandoc-resolved HTML ref anchors into MyST ``{ref}``
        # directives BEFORE stripping HTML. The pre-resolved number in
        # the ``<a>`` body is chapter-unaware (pandoc only sees the
        # split-per-chapter file, not the book), but the
        # ``data-reference`` attribute preserves the original label —
        # MyST can resolve it with full project context (closes #33).
        cap = re.sub(
            r'<a[^>]*data-reference="([^"]+)"[^>]*>[^<]*</a>',
            lambda m: '{ref}`' + convert_label_colons(m.group(1)) + '`',
            cap,
        )
        cap = re.sub(r'<[^>]+>', '', cap).strip()
        # The doubled-noun strippers ran earlier in ``process_file``;
        # any ``§ Section`` / ``Chapter Chapter`` produced *here* by
        # the ref-conversion above would otherwise survive into the
        # final caption. Re-run them locally on the caption string.
        cap = strip_doubled_noun_refs(cap)
        cap = strip_doubled_section_symbol(cap)
        return cap

    # Determine which labels are actually referenced by {numref} elsewhere in
    # the chapter so that nested-subfigure handling can choose the right
    # :name: for each emitted figure. MyST collapses adjacent
    # ``(parent)=`` anchors into the following figure's name, so we cannot
    # emit both a parent anchor *and* a child :name: — we must pick one per
    # figure based on actual cross-references.
    referenced_labels = set(re.findall(r'\{numref\}`([^`]+)`', text))

    # Pandoc emits ``<embed src=...>`` for ``\input{tikz/...}`` figures and
    # ``<img src=...>`` for ordinary ``\includegraphics`` references. Both
    # shapes signal a real image source — without a unified match, plain
    # ``\includegraphics`` figures get mis-classified as TikZ admonitions
    # (GH #25).
    _figure_src_re = re.compile(r'<(?:embed|img)[^>]*src="([^"]+)"')

    # Pass 1: nested subfigure pattern (parent with one or more labelled inner figures).
    # Each inner figure carries its own id; the outer figure has its own id and trailing caption.
    nested_pattern = re.compile(
        r'<figure[^>]*id="(?P<outer_id>[^"]+)"[^>]*>\s*'
        r'(?P<inner>(?:<figure[^>]*>.*?</figure>\s*)+)'
        r'<figcaption>(?P<outer_cap>.*?)</figcaption>\s*'
        r'</figure>',
        re.DOTALL,
    )

    def make_figure(label, src, caption):
        if '/' not in src:
            src = 'figures/' + src
        lines = ['```{figure} ' + src]
        if label:
            lines.append(f':name: {label}')
        lines.append('')
        if caption:
            lines.append(caption)
        lines.append('```')
        return '\n'.join(lines)

    def replace_nested(m):
        outer_label = convert_label_colons(m.group('outer_id'))
        inner_blob = m.group('inner')
        inner_matches = list(
            re.finditer(r'<figure[^>]*>.*?</figure>', inner_blob, re.DOTALL)
        )
        parts = []
        outer_assigned = False
        for idx, inner_match in enumerate(inner_matches):
            inner_block = inner_match.group(0)
            id_match = re.search(r'<figure[^>]*id="([^"]+)"', inner_block)
            child_label = (
                convert_label_colons(id_match.group(1)) if id_match else None
            )
            # Pick the :name: per figure: prefer a label that is actually
            # referenced. The parent label can only attach to one figure, so
            # we give it to the first child that is itself unreferenced.
            chosen = child_label
            if (
                not outer_assigned
                and outer_label
                and outer_label in referenced_labels
                and (child_label is None or child_label not in referenced_labels)
            ):
                chosen = outer_label
                outer_assigned = True
            # Fallback: an unlabeled subfigure that didn't inherit the outer
            # label would otherwise vanish in `resolve_tikz_figures` (no
            # :name: → "orphaned" branch). Auto-generate ``{outer}-{a,b,…}``
            # so each subfigure survives with a distinct, cross-refable
            # label. GH #17.
            if chosen is None and outer_label:
                chosen = f"{outer_label}-{chr(ord('a') + idx)}"

            embed_match = _figure_src_re.search(inner_block)
            caption = extract_caption(inner_block)
            if embed_match:
                # Real raster/vector image — emit a {figure} directly
                # from the embed src. Skips the TikZ-placeholder round
                # trip, which would silently drop unlabeled subfigures
                # whose label isn't in TIKZ_FIGURE_MAP. GH #17.
                parts.append(make_figure(chosen, embed_match.group(1), caption))
            else:
                # No image source (e.g. \input{tikz/...}) — keep the
                # admonition placeholder so TIKZ_FIGURE_MAP can resolve it.
                parts.append(make_admonition(chosen, caption))
        return '\n'.join(parts)

    text = nested_pattern.sub(replace_nested, text)

    # Pass 2: any remaining (non-nested) figure blocks. Mirror Pass 1's
    # image-source check — when a real ``<img>``/``<embed>`` src is
    # present (the common ``\includegraphics`` case), emit a ``{figure}``
    # directly; only fall back to the TikZ admonition when no image
    # source is found. GH #25.
    def replace_html_figure(m):
        block = m.group(0)
        id_match = re.search(r'<figure[^>]*id="([^"]+)"', block)
        label = convert_label_colons(id_match.group(1)) if id_match else None
        caption = extract_caption(block)
        embed_match = _figure_src_re.search(block)
        if embed_match:
            return make_figure(label, embed_match.group(1), caption)
        return make_admonition(label, caption)

    text = re.sub(
        r'<figure[^>]*>.*?</figure>',
        replace_html_figure,
        text,
        flags=re.DOTALL,
    )
    return text


# ── TikZ figure resolution ───────────────────────────────────────────────────

# Map TikZ admonition placeholder labels to actual figure paths.
#
# Populated from the project's tikz_overrides.py file at load time (see
# config.yaml: `tikz_overrides`). Keys are the `:name:` labels emitted by the
# preprocessor for `\input{tikz/...}` references; values are
# `(image_path, optional_caption_override)` tuples.
#
# Empty by default; projects without TikZ leave it empty.
TIKZ_FIGURE_MAP: dict = {}

# Inline tikzcd math blocks to replace with image directives.
# Keyed by chapter stem; each entry matches a $$ tikzcd $$ block.
# Populated from tikz_overrides.py.
TIKZCD_INLINE_MAP: dict = {}


def resolve_tikz_figures(text: str, stem: str) -> str:
    """Replace TikZ admonition placeholders with actual figure directives.

    Also handles:
    - Stray HTML remnants from subfigure environments
    - Unlabeled TikZ admonition blocks (orphaned sub-panels)
    - Inline tikzcd math blocks → {image} directives
    """
    lines = text.split('\n')
    result = []
    i = 0

    while i < len(lines):
        line = lines[i]

        # Match TikZ admonition placeholder
        if line.strip() == '```{admonition} Figure (TikZ — needs manual conversion)':
            i += 1
            label = None
            caption_lines = []
            while i < len(lines) and lines[i].strip() != '```':
                if lines[i].startswith(':name:'):
                    label = lines[i].split(':name:')[1].strip()
                elif lines[i].strip():
                    caption_lines.append(lines[i].strip())
                i += 1
            if i < len(lines):
                i += 1  # skip closing ```

            if label and label in TIKZ_FIGURE_MAP:
                path, caption_override = TIKZ_FIGURE_MAP[label]
                caption = caption_override or ' '.join(caption_lines)
                result.append(f'```{{figure}} {path}')
                result.append(f':name: {label}')
                result.append('')
                if caption:
                    result.append(caption)
                result.append('```')
            elif label:
                # Unknown label — keep as placeholder
                result.append('```{admonition} Figure (TikZ — needs manual conversion)')
                result.append(f':name: {label}')
                result.append('')
                for cl in caption_lines:
                    result.append(cl)
                result.append('```')
            else:
                # Unlabeled — orphaned sub-panel from subfigure, skip
                pass
            continue

        # Remove stray HTML figcaption remnants from subfigure environments
        if '<figcaption>' in line:
            # Consume until closing tag (may span multiple lines)
            while i < len(lines) and '</figcaption>' not in lines[i]:
                i += 1
            i += 1
            continue
        if line.strip() == '</figure>':
            i += 1
            continue

        result.append(line)
        i += 1

    text = '\n'.join(result)

    # Handle inline tikzcd math blocks. The replacement is wrapped in a
    # lambda so ``re.sub`` treats it as a literal string — authors write
    # LaTeX-flavoured Markdown in these override entries (``\hat``,
    # ``\Phi``, ``\beta``, …) and Python 3.13 hardened the regex parser
    # to reject those as bad escapes when passed as a replacement string
    # (issue #7). The lambda form bypasses escape parsing entirely.
    # Backreferences (``\1``, ``\g<name>``) are not supported in this
    # form; no current consumer uses them.
    if stem in TIKZCD_INLINE_MAP:
        for entry in TIKZCD_INLINE_MAP[stem]:
            text = re.sub(
                entry['pattern'],
                lambda m, r=entry['replacement']: r,
                text,
                flags=re.DOTALL,
            )

    return text


# join_split_inline_math moved to transforms/math.py (P3a)

# strip_doubled_noun_refs moved to transforms/refs.py (P3a)

# Per-book extension of the doubled-noun list. Populated by
# ``apply_config`` from ``doubled_noun_refs`` in config.yaml. Books
# with custom theorem-class nouns extend without forking.
_EXTRA_DOUBLED_NOUN_REFS: list[tuple[str, str]] = []


# Label-prefix families for which qe-v5 auto-renders a noun ("Section
# X.Y" / "Paragraph X.Y" / "Example X.Y") before the ref. Authors
# sometimes prefix the ref with a literal ``§`` (LaTeX's ``\S``); the
# combination renders as "§ Section X.Y" / "§ Example X.Y" which
# double-counts the noun.
#
# Mostly section-style prefixes, plus ``eg-`` after a dp2 instance of
# the author writing ``\S\ref{eg:foo}`` (semantic mismatch — `\S` is the
# section symbol, but they pointed it at an example). See lesson 016.
# _DOUBLED_SECTION_SYMBOL_PREFIXES moved to transforms/refs.py (P3a)

# strip_doubled_section_symbol moved to transforms/refs.py (P3a)

# strip_footnote_refs moved to transforms/refs.py (P3a)

# strip_blank_lines_in_math moved to transforms/math.py (P3a)

# ensure_blank_after_display_math moved to transforms/math.py (P3a)

# cleanup_typography moved to transforms/typography.py (P3a)


# ── minted listings → {code-block} ───────────────────────────────────────────
#
# Listing bodies are intercepted before pandoc by
# scripts/_apply_listing_markers.py, which emits an HTML-comment marker
# carrying the language, source path, line range, label, and caption.
# Here we decode the marker, read the referenced source file, slice the
# requested line range, and emit a MyST ``code-block`` directive whose
# ``:name:`` enables ``{numref}`list-foo``` cross-references.
#
# Reference: book-dp1/mystmd/scripts/postprocess.py::resolve_listings.

# Base directory for resolving ``\inputminted`` paths. Populated by
# apply_config() from config.yaml's ``source_code_base`` (default: source_dir).
_LISTING_SOURCE_BASE: Path | None = None


def resolve_listings(text: str) -> str:
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

    base = _LISTING_SOURCE_BASE

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


# ── algorithm2e → {prf:algorithm} ────────────────────────────────────────────
#
# Algorithm bodies are intercepted before pandoc by
# scripts/_apply_algorithm_markers.py, which base64-encodes them inside an
# HTML comment marker. Here we decode the markers, parse the algorithm2e
# control commands (``\While``, ``\For``, ``\KwIn`` etc.) into nested bullet
# lists, and emit a {prf:algorithm} directive.
#
# Reference: book-dp1/mystmd/scripts/postprocess.py.

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
            emit_header(f'for {arg}:' if arg else 'for:')
            if text:
                emit(text)
        elif kw == 'FORALL':
            stack.append('FOR')  # closed by same \ENDFOR
            emit_header(f'for all {arg}:' if arg else 'for all:')
            if text:
                emit(text)
        elif kw == 'ENDFOR':
            close_block({'FOR'})
            if text:
                emit(text)
        elif kw == 'WHILE':
            stack.append('WHILE')
            emit_header(f'while {arg}:' if arg else 'while:')
            if text:
                emit(text)
        elif kw == 'ENDWHILE':
            close_block({'WHILE'})
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
    # Balanced-brace unwrap — naive [^}]* stops at the first } and
    # mangles nested math like \textbf{$\mathcal{Q}$ X} (GH #21).
    s = _unwrap_text_macro(s, 'navy',   '**{}**')
    s = _unwrap_text_macro(s, 'textbf', '**{}**')
    # ``\textnormal{...}`` is LaTeX's way to drop into upright text inside
    # math mode; in an algorithm condition like ``\While{\textnormal{true}}``
    # the wrapper has no markdown equivalent — unwrap it. (FOLLOWUP #014, Gap B)
    s = _unwrap_text_macro(s, 'textnormal', '{}')

    # Repeatedly expand control blocks (innermost first via simple loop).
    def expand_one(text: str) -> tuple[str, bool]:
        # Two-arg control blocks.
        for cmd, header_fmt in (
            ('While',   'while {}:'),
            ('For',     'for {}:'),
            ('ForEach', 'for each {}:'),
            ('If',      'if {}:'),
            ('uIf',     'if {}:'),
            ('ElseIf',  'else if {}:'),
            ('lIf',     'if {}: {}'),
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
            replacement = fmt.format(arg)
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
            return text[: m.start()] + fmt.format(arg) + text[m.end() :], True

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
        for line in p.split('\n'):
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

    return '\n'.join(out_lines).strip()


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
                    val = val[1:-1]
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


def resolve_algorithms(text: str) -> str:
    """Replace ALGORITHM markers with ``{prf:algorithm}`` directives.

    Marker format (emitted by _apply_algorithm_markers.py):
        <!--ALGORITHM name=NAME title=TITLE TEXT body=BASE64-->

    The body is base64-encoded so pandoc passes it through verbatim
    (otherwise pandoc would strip ``\\;`` and reformat ``\\While`` etc.).
    Pandoc may escape ``<`` to ``\\<``; the regex tolerates both forms.
    """
    pattern = re.compile(
        r'\\?<!--ALGORITHM\s+'
        r'name=(?P<name>\S+)\s+'
        r'title=(?P<title>.*?)\s+'
        r'body=(?P<body>[A-Za-z0-9+/=]+)--\\?>',
        re.DOTALL,
    )

    def repl(m: re.Match) -> str:
        name = m.group('name').strip()
        title = (m.group('title') or '').strip()
        body_b64 = m.group('body').strip()
        try:
            body = base64.b64decode(body_b64).decode('utf-8')
        except Exception:
            body = ''
        converted = _algo_convert_body(body)
        out = []
        if title:
            out.append(f'```{{prf:algorithm}} {title}')
        else:
            out.append('```{prf:algorithm}')
        out.append(f':label: {name}')
        out.append('')
        out.append(converted)
        out.append('```')
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


# compress_directive_whitespace moved to transforms/typography.py (P3a)


def apply_postprocess_rewrites(text: str, stem: str) -> str:
    """Apply book-specific Markdown rewrites declared in
    ``config.postprocess.rewrites``.

    Runs after all generic transforms and ``add_frontmatter`` — the
    last thing before the file is written. The use case is editorial
    decisions the tool can't infer from LaTeX (e.g. promoting a
    book's ``**Bold heading**`` pseudo-section to a real ``## H2``
    only in specific chapters where that pattern is known to be a
    heading rather than emphasis).

    Each rewrite scoped via ``stems:`` runs only on the matching
    chapter; unscoped rewrites run everywhere. Patterns are Python
    regexes with ``re.MULTILINE`` so ``^...$`` matches line
    boundaries — the common shape for editorial-heading patterns.
    """
    for pattern, replacement, stems in POSTPROCESS_REWRITES:
        if stems is not None and stem not in stems:
            continue
        text = pattern.sub(replacement, text)
    return text


def add_frontmatter(text: str, title: str, style: str | None = None) -> str:
    """Emit frontmatter / chapter heading in the configured style.

    Two valid MyST conventions, both round-trip:

    - ``absorbed`` (default, dp2 style): pull the ``(label)= / # Title``
      heading into a YAML block at the top of the file.

      .. code-block:: yaml

          ---
          title: "Foo"
          label: c-foo
          ---

    - ``standalone`` (dp1 style): leave the heading in the body and emit
      no YAML.

      .. code-block:: markdown

          (c-foo)=
          # Foo

    ``style`` overrides the module-level ``_FRONTMATTER_STYLE`` for this
    one call — used by ``process_file`` to honour per-chapter overrides
    declared in ``config.chapters[].frontmatter_style`` or
    ``config.extra_files[].frontmatter_style``.

    Idempotent: re-processing a file already in either style is a no-op
    (modulo title updates from config). Existing YAML ``label:`` values
    are preserved so chapter cross-references like ``{prf:ref}`c-egs```
    keep resolving even if the LaTeX source no longer carries the label.
    """
    effective_style = style if style is not None else _FRONTMATTER_STYLE
    # Strip any existing YAML frontmatter, capturing label: if present so
    # we don't lose it across re-runs.
    existing_label = None
    while text.startswith('---\n'):
        end = text.find('\n---\n', 4)
        if end == -1:
            break
        block = text[4:end]
        if existing_label is None:
            lm = re.search(r'^label:\s*(\S+)\s*$', block, re.MULTILINE)
            if lm:
                existing_label = lm.group(1)
        text = text[end + 5:].lstrip('\n')

    heading_m = re.match(r'\(([^)]+)\)=\s*\n# (.+)\n', text)
    # When the source has both a heading auto-id AND an explicit
    # \label{...} on the chapter (e.g. ``\chapter*{Foo}\n\label{c:foo}``,
    # which pandoc cannot fold into the heading's ``{#id}`` and emits
    # separately as ``[]{#c:foo}``), the explicit body anchor lands on
    # the line(s) following the heading. Prefer the explicit label as
    # the canonical cross-ref target — that's the identifier the author
    # chose for ``\ref{}``.
    #
    # Only treat the body anchor as the chapter's if it is followed by
    # ordinary content. A ``(slug)=`` followed by another markdown
    # heading (``## Section``, ``### Subsection``) is that section's
    # label, not the chapter's, and must not be promoted to the
    # chapter's frontmatter (would steal e.g. the first section's label).
    following_anchor_label = None
    if heading_m:
        rest = text[heading_m.end():].lstrip('\n')
        follow_m = re.match(r'\(([^)]+)\)=\s*\n(.*?)(?:\n|$)', rest)
        if follow_m and not re.match(r'#{1,6}\s', follow_m.group(2)):
            following_anchor_label = follow_m.group(1)

    if existing_label is not None:
        label = existing_label
    elif heading_m:
        label = following_anchor_label or heading_m.group(1)
    else:
        label = None

    if effective_style == 'standalone':
        # Body keeps its ``(label)=\n# Title`` heading; just ensure one
        # exists (synthesise from config if the body lost it during a
        # round-trip through an absorbed-style YAML block).
        if heading_m:
            if following_anchor_label is not None:
                # Replace the heading auto-id with the explicit label
                # and drop the duplicate body anchor.
                title_text = heading_m.group(2)
                rest_after = text[heading_m.end():].lstrip('\n')
                rest_after = re.sub(
                    r'^\([^)]+\)=\s*\n+', '', rest_after, count=1
                )
                return f'({label})=\n# {title_text}\n\n' + rest_after
            return text
        header = ''
        if label:
            header += f'({label})=\n'
        header += f'# {title}\n\n'
        return header + text

    # absorbed (default): strip the heading from the body and emit YAML.
    # lstrip newlines so the result is byte-identical across re-runs (the
    # YAML-strip path above lstrips already; this matches it).
    if heading_m:
        text = text[heading_m.end():].lstrip('\n')
        if following_anchor_label is not None:
            text = re.sub(r'^\([^)]+\)=\s*\n+', '', text, count=1)
    else:
        # No body anchor + heading pair to absorb (the common
        # ``\chapter{Preface}`` case where pandoc emits a bare ``# Title``
        # with no attribute block). If that bare H1 exactly matches the
        # configured frontmatter title, drop it — otherwise we'd render
        # two identical headings in a row (issue #3). Mismatched titles
        # are left alone: the author wrote two distinct things.
        bare_h1 = re.match(r'#\s+' + re.escape(title) + r'\s*\n+', text)
        if bare_h1:
            text = text[bare_h1.end():]
    frontmatter = f'---\ntitle: "{title}"\n'
    if label:
        frontmatter += f'label: {label}\n'
    frontmatter += '---\n\n'
    return frontmatter + text


# Book-specific Markdown rewrites applied after the generic transforms.
# Each entry is ``(compiled_regex, replacement, stems_or_None)``.
# - ``stems_or_None=None``: rewrite applies to every chapter (global).
# - ``stems_or_None={'a', 'b'}``: rewrite applies only to those stems.
# Populated from ``config.postprocess.rewrites`` at runtime.
POSTPROCESS_REWRITES: list = []


# Chapter titles mapping — populated from config.yaml at runtime.
CHAPTER_TITLES: dict = {}

# Per-stem frontmatter_style override. A book with mixed conventions (e.g.
# dp1: numbered chapters in ``standalone``, front-matter in ``absorbed``)
# can opt individual stems out of the global default. Populated from
# ``chapters[].frontmatter_style`` / ``extra_files[].frontmatter_style``
# in config.yaml. Stems not present here inherit ``_FRONTMATTER_STYLE``.
CHAPTER_STYLES: dict = {}

# Frontmatter style: 'absorbed' (YAML block, dp2 style — the default) or
# 'standalone' ((label)= + # heading, dp1 style). Populated by apply_config.
_FRONTMATTER_STYLE: str = 'absorbed'

# Whitespace compression: 'readable' (default; keep blank lines around
# directives for source readability) or 'compact' (dp1 style; strip blank
# lines after :label: and between adjacent directives). Populated by
# apply_config.
_WHITESPACE_STYLE: str = 'readable'


# ── Config loading ───────────────────────────────────────────────────────────

def load_config(config_path: Path) -> dict:
    """Load YAML config. Uses PyYAML if available, else a minimal fallback."""
    text = config_path.read_text(encoding='utf-8')
    try:
        import yaml  # type: ignore
        return yaml.safe_load(text)
    except ImportError:
        # Minimal YAML fallback for the subset we use (no anchors, no flow style).
        # Recommend installing PyYAML for production use.
        raise SystemExit(
            "PyYAML is required to load config. Install with: pip install pyyaml"
        )


def load_overrides(overrides_path: Path) -> None:
    """Load TIKZ_FIGURE_MAP and TIKZCD_INLINE_MAP from a project .py file."""
    global TIKZ_FIGURE_MAP, TIKZCD_INLINE_MAP
    spec = importlib.util.spec_from_file_location("project_overrides", overrides_path)
    if spec is None or spec.loader is None:
        raise SystemExit(f"Cannot load overrides file: {overrides_path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    TIKZ_FIGURE_MAP = getattr(mod, 'TIKZ_FIGURE_MAP', {})
    TIKZCD_INLINE_MAP = getattr(mod, 'TIKZCD_INLINE_MAP', {})


# Top-level config schema. Keys map to ``(allowed_types, required?)``. A
# tuple of types means "one of these"; ``type(None)`` is allowed for keys
# that may be nullable. The validator's main value is catching typos
# (e.g. ``whitespace_comression``) — easy mistake, silent today.
_CONFIG_SCHEMA: dict = {
    'source_dir':             ((str,),               True),
    'output_dir':             ((str,),               False),
    'tmp_dir':                ((str,),               False),
    'chapters':               ((list, type(None)),   False),
    'extra_files':            ((list, type(None)),   False),
    'bibliography':           ((str, type(None)),    False),
    'figures_dir':            ((str, type(None)),    False),
    'source_code_base':       ((str, type(None)),    False),
    'frontmatter_style':      ((str,),               False),
    'whitespace_compression': ((str,),               False),
    'extra_environments':     ((dict, type(None)),   False),
    'skip_environments':      ((list, type(None)),   False),
    'cross_ref_routing':      ((list, type(None)),   False),
    'doubled_noun_refs':      ((list, type(None)),   False),
    'preprocess':             ((dict, type(None)),   False),
    'postprocess':            ((dict, type(None)),   False),
    'tikz_overrides':         ((str, type(None)),    False),
    'validate':               ((dict, type(None)),   False),
}


def validate_config(config: dict) -> None:
    """Reject unknown keys and bad types. Surfaces config typos that
    would otherwise be silently ignored (``whitespace_comression``,
    ``front_matter_style``, etc.).
    """
    if not isinstance(config, dict):
        raise SystemExit(
            f"config root must be a mapping, got {type(config).__name__}"
        )

    unknown = sorted(set(config) - set(_CONFIG_SCHEMA))
    if unknown:
        # Suggest the closest known key for each unknown one, à la cargo.
        from difflib import get_close_matches
        hints = []
        for k in unknown:
            suggestions = get_close_matches(k, _CONFIG_SCHEMA.keys(), n=1)
            if suggestions:
                hints.append(f"  {k!r}  (did you mean {suggestions[0]!r}?)")
            else:
                hints.append(f"  {k!r}")
        raise SystemExit(
            "config has unknown top-level keys:\n" + "\n".join(hints)
        )

    for key, (types, required) in _CONFIG_SCHEMA.items():
        if key not in config:
            if required:
                raise SystemExit(f"config is missing required key: {key!r}")
            continue
        value = config[key]
        if not isinstance(value, types):
            type_names = " or ".join(
                'null' if t is type(None) else t.__name__ for t in types
            )
            raise SystemExit(
                f"config.{key} must be {type_names}, got {type(value).__name__}"
            )

    # Nested validation for chapters / extra_files: each entry needs at
    # minimum a ``stem``. ``frontmatter_style`` is optional but, when
    # present, must be one of the two recognised styles — same vocabulary
    # as the top-level ``frontmatter_style`` key.
    for list_key in ('chapters', 'extra_files'):
        for i, entry in enumerate(config.get(list_key) or []):
            if not isinstance(entry, dict) or 'stem' not in entry:
                raise SystemExit(
                    f"config.{list_key}[{i}] must be a mapping with a 'stem' key"
                )
            style = entry.get('frontmatter_style')
            if style is not None and style not in ('absorbed', 'standalone'):
                raise SystemExit(
                    f"config.{list_key}[{i}].frontmatter_style must be "
                    f"'absorbed' or 'standalone', got {style!r}"
                )


def apply_config(config: dict, base_dir: Path | None = None) -> None:
    """Populate module-level state from a loaded config dict.

    ``base_dir`` is the directory containing config.yaml; relative paths in
    config (``source_dir``, ``source_code_base``) are resolved against it.
    Tests that call ``apply_config`` without a base_dir won't get listing
    resolution, which is fine — listings are an opt-in feature.
    """
    global CHAPTER_TITLES, CHAPTER_STYLES, POSTPROCESS_REWRITES
    global _LISTING_SOURCE_BASE, _FRONTMATTER_STYLE, _WHITESPACE_STYLE
    global ENV_MAP, ENV_SKIP
    validate_config(config)
    CHAPTER_TITLES = {
        entry['stem']: entry.get('title', entry['stem'])
        for entry in (config.get('chapters') or []) + (config.get('extra_files') or [])
    }
    CHAPTER_STYLES = {
        entry['stem']: entry['frontmatter_style']
        for entry in (config.get('chapters') or []) + (config.get('extra_files') or [])
        if 'frontmatter_style' in entry
    }

    # Extend the env→directive map with project-specific environments. Use
    # for theorem-like environments not in the default ENV_MAP (e.g.
    # ``Conjecture: prf:conjecture``, ``Notation: prf:remark``). Project
    # entries override defaults if the same key appears in both.
    extra_envs = config.get('extra_environments') or {}
    if not isinstance(extra_envs, dict):
        raise SystemExit(
            f"config.extra_environments must be a mapping, got {type(extra_envs).__name__}"
        )
    ENV_MAP = {**ENV_MAP, **extra_envs}

    # Extend the "div wrappers to strip" set with project-specific
    # environments — e.g. layout commands that pandoc preserves as ``:::``
    # blocks but have no MyST equivalent (``columns``, ``framed`` …).
    skip_envs = config.get('skip_environments') or []
    if not isinstance(skip_envs, (list, tuple, set)):
        raise SystemExit(
            f"config.skip_environments must be a list, got {type(skip_envs).__name__}"
        )
    ENV_SKIP = ENV_SKIP | set(skip_envs)

    # Per-book extension of the label-prefix → role routing used by
    # ``convert_cross_references.make_ref``. Each entry: ``{prefix: "X",
    # role: "numref|ref|eq|prf:ref"}``. ``prefix`` may be a string
    # ("lst" expands to ("lst:", "lst-")) or an explicit list. Useful
    # when a book uses a non-default label convention (e.g. ``lst:`` for
    # listings instead of the QuantEcon default ``list:``).
    global _EXTRA_CROSS_REF_ROUTING
    _EXTRA_CROSS_REF_ROUTING = []
    for i, rule in enumerate(config.get('cross_ref_routing') or []):
        if not isinstance(rule, dict):
            raise SystemExit(
                f"config.cross_ref_routing[{i}] must be a mapping"
            )
        if 'prefix' not in rule or 'role' not in rule:
            raise SystemExit(
                f"config.cross_ref_routing[{i}] requires 'prefix' and 'role'"
            )
        role = rule['role']
        if not isinstance(role, str):
            raise SystemExit(
                f"config.cross_ref_routing[{i}].role must be a string"
            )
        raw = rule['prefix']
        if isinstance(raw, str):
            # ``"lst"`` expands to both colon- and hyphen-bearing forms,
            # mirroring how labels arrive after ``convert_label_colons``.
            prefixes = (f'{raw}:', f'{raw}-')
        elif isinstance(raw, list) and all(isinstance(p, str) for p in raw):
            prefixes = tuple(raw)
        else:
            raise SystemExit(
                f"config.cross_ref_routing[{i}].prefix must be a string "
                "or list of strings"
            )
        _EXTRA_CROSS_REF_ROUTING.append((prefixes, role))

    # Per-book extension of the doubled-noun list used by
    # ``strip_doubled_noun_refs``. Each entry: ``{noun: "X", prefix: "x-"}``.
    # Useful when a book defines custom theorem classes with their own
    # display nouns ("Claim", "Conjecture", "Fact" …).
    global _EXTRA_DOUBLED_NOUN_REFS
    _EXTRA_DOUBLED_NOUN_REFS = []
    for i, rule in enumerate(config.get('doubled_noun_refs') or []):
        if not isinstance(rule, dict):
            raise SystemExit(
                f"config.doubled_noun_refs[{i}] must be a mapping"
            )
        noun = rule.get('noun')
        prefix = rule.get('prefix')
        if not isinstance(noun, str) or not isinstance(prefix, str):
            raise SystemExit(
                f"config.doubled_noun_refs[{i}] requires string 'noun' "
                "and 'prefix' keys"
            )
        _EXTRA_DOUBLED_NOUN_REFS.append((noun, prefix))

    style = config.get('frontmatter_style', 'absorbed')
    if style not in ('absorbed', 'standalone'):
        raise SystemExit(
            f"config.frontmatter_style must be 'absorbed' or 'standalone', got {style!r}"
        )
    _FRONTMATTER_STYLE = style

    ws = config.get('whitespace_compression', 'readable')
    if ws not in ('readable', 'compact'):
        raise SystemExit(
            f"config.whitespace_compression must be 'readable' or 'compact', got {ws!r}"
        )
    _WHITESPACE_STYLE = ws

    # Book-specific Markdown rewrites. Each entry: { from: regex, to: repl,
    # stems?: [stem1, stem2] }. Compile patterns once at config load.
    post_section = config.get('postprocess') or {}
    if not isinstance(post_section, dict):
        raise SystemExit(
            f"config.postprocess must be a mapping, got {type(post_section).__name__}"
        )
    raw_rewrites = post_section.get('rewrites') or []
    if not isinstance(raw_rewrites, list):
        raise SystemExit(
            f"config.postprocess.rewrites must be a list, got {type(raw_rewrites).__name__}"
        )
    POSTPROCESS_REWRITES = []
    for i, rule in enumerate(raw_rewrites):
        if not isinstance(rule, dict):
            raise SystemExit(
                f"config.postprocess.rewrites[{i}] must be a mapping"
            )
        if 'from' not in rule or 'to' not in rule:
            raise SystemExit(
                f"config.postprocess.rewrites[{i}] requires 'from' and 'to' keys"
            )
        if not isinstance(rule['from'], str) or not isinstance(rule['to'], str):
            raise SystemExit(
                f"config.postprocess.rewrites[{i}]: 'from' and 'to' must be strings"
            )
        stems_field = rule.get('stems')
        if stems_field is not None:
            if (not isinstance(stems_field, list)
                    or not all(isinstance(s, str) for s in stems_field)):
                raise SystemExit(
                    f"config.postprocess.rewrites[{i}].stems must be a list of strings"
                )
            stems_set = frozenset(stems_field)
        else:
            stems_set = None
        try:
            compiled = re.compile(rule['from'], re.MULTILINE)
        except re.error as exc:
            raise SystemExit(
                f"config.postprocess.rewrites[{i}]: bad regex {rule['from']!r}: {exc}"
            )
        POSTPROCESS_REWRITES.append((compiled, rule['to'], stems_set))

    if base_dir is not None:
        # source_code_base anchors paths inside \inputminted{lang}{path}.
        # Defaults to source_dir so dp1-style layouts (``\inputminted{julia}
        # {../source_code_jl/foo.jl}`` from a tex file in ``book/``) work
        # without extra config.
        src_base = config.get('source_code_base') or config.get('source_dir', '.')
        _LISTING_SOURCE_BASE = (base_dir / src_base).resolve()


def process_text(text: str, stem: str, title: str | None = None,
                 *, style: str | None = None) -> str:
    """Pure in-memory transform pipeline. Same order as ``process_file``;
    no file I/O. Extracted so golden-file tests can exercise the full
    pipeline against checked-in fixtures (P0c).

    Order matters:
      - fix_text_dollar first (before eq conversion changes $$ structure)
      - epigraphs (removes ::: blocks before env conversion)
      - environments before labels (directive labels handled in context)
      - equations before cross-refs (so labels are extracted first)
      - cross-refs before figures (captions may contain cross-refs)

    The canonical sequence is locked in ``tests/test_pipeline_order.py``
    (lesson 008). Update both places together if you intentionally reorder.
    """
    global _last_exercise_label, _exercise_counter, _chapter_prefix
    _last_exercise_label = None
    _exercise_counter = 0
    # Chapter prefix for auto-generated labels: strip leading 'ch_' if present.
    _chapter_prefix = stem[3:] if stem.startswith('ch_') else stem

    text = strip_pandoc_html_separators(text)
    text = fix_text_dollar(text)
    text = convert_epigraphs(text)
    # convert_simple_tables MUST run before convert_environment_divs (GH #27):
    # tabulars wrapped in \begin{center}…\end{center} are rendered by pandoc
    # as multiline_tables inside ``::: center`` fenced divs, and the #24
    # bound-scan fix relies on the ``:::`` boundary to know where the table
    # region ends. convert_environment_divs strips ``::: center`` (via
    # ENV_SKIP), so once it has run the boundary is gone and the scan fuses
    # adjacent tables again. Order the two passes so the boundary survives
    # until the table pass has used it.
    text = convert_pandoc_attr_code_blocks(text)   # lstlisting → {code-block} (closes #31)
    text = convert_simple_tables(text)
    text = convert_environment_divs(text)
    text = convert_description_lists(text)         # decode DESCITEM markers (lesson 022)
    text = convert_equations(text)
    text = decode_natbib_markers(text)              # before cross-refs (lesson 020)
    text = convert_cross_references(text)
    text = strip_doubled_noun_refs(text)           # needs MyST refs in place
    text = strip_doubled_section_symbol(text)      # qe-v5 § Section dedupe
    text = convert_figures(text)
    text = convert_html_figures(text)
    text = resolve_tikz_figures(text, stem)
    text = convert_section_labels(text)
    text = convert_citations(text)
    text = convert_standalone_labels(text)
    # Listings and algorithms run LATE so source-code bodies don't get
    # touched by the citation / cross-ref / typography transforms above
    # (Julia ``@views`` etc. would otherwise be eaten by convert_citations).
    text = resolve_listings(text)                  # decode minted markers
    text = resolve_algorithms(text)                # decode algorithm2e markers
    text = resolve_algorithmics(text)              # decode standalone algorithmicx markers (lesson 023)
    text = join_split_inline_math(text)
    text = ensure_blank_after_display_math(text)   # adds blank lines
    text = cleanup_typography(text)                # caps blank-line runs; strips \qedhere
    text = strip_blank_lines_in_math(text)         # MUST run AFTER \qedhere removal (issue #11)
    text = strip_footnote_refs(text)               # operates on cleaned text
    text = compress_directive_whitespace(text)     # opt-in (compact mode)

    resolved_title = title if title is not None else stem
    text = add_frontmatter(text, resolved_title, style=style)
    text = apply_postprocess_rewrites(text, stem)
    return text


def process_file(input_path: Path, output_path: Path = None):
    """Process a single pandoc markdown file into MyST."""
    stem = input_path.stem
    text = input_path.read_text(encoding='utf-8')
    title = CHAPTER_TITLES.get(stem, stem)
    style = CHAPTER_STYLES.get(stem)
    text = process_text(text, stem, title, style=style)

    out = output_path or input_path
    out.write_text(text, encoding='utf-8')
    print(f'  Processed: {input_path.name} → {out.name}')


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--config', type=Path, required=True,
                        help='Path to config.yaml')
    parser.add_argument('inputs', nargs='*', type=Path,
                        help='Specific .md files to process (default: all chapters in config)')
    args = parser.parse_args()

    config_path = args.config.resolve()
    config = load_config(config_path)
    base_dir = config_path.parent
    apply_config(config, base_dir)
    output_dir = (base_dir / config.get('output_dir', '.')).resolve()

    # Load TikZ overrides if configured
    tikz_overrides = config.get('tikz_overrides')
    if tikz_overrides:
        overrides_path = (base_dir / tikz_overrides).resolve()
        if overrides_path.exists():
            load_overrides(overrides_path)
        else:
            print(f'  WARN: tikz_overrides file not found: {overrides_path}', file=sys.stderr)

    if args.inputs:
        for path in args.inputs:
            process_file(path)
        return

    # Process every chapter + extra file from config
    all_files = (config.get('chapters') or []) + (config.get('extra_files') or [])
    for entry in all_files:
        md = output_dir / f"{entry['stem']}.md"
        if md.exists():
            process_file(md)
        else:
            print(f'  WARN: {md} not found, skipping', file=sys.stderr)


if __name__ == '__main__':
    main()
