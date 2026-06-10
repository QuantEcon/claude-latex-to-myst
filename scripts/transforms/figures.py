"""Figure transforms.

Three shapes of figure pandoc emits:

- Markdown image syntax ``![cap](path){#id width=...}`` — from plain
  ``\\includegraphics``. Handled by ``convert_figures``.
- HTML ``<figure id="X"><img/><figcaption>...</figcaption></figure>``
  — emitted for TikZ-shaped placeholders and embed forms. Handled by
  ``convert_html_figures``.
- HTML nested subfigure (outer ``<figure>`` wrapping inner ones) — the
  subfigure-package shape. Same function, separate nested-pattern
  logic with the parent-label-takes-first-child-slot semantics from
  lesson 021.

``resolve_tikz_figures`` replaces TikZ admonition placeholders with
``{figure}`` directives keyed by ``TIKZ_FIGURE_MAP`` (per-project map
populated from ``tikz_overrides.py``).

State coupling: ``resolve_tikz_figures`` reads
``postprocess.TIKZ_FIGURE_MAP`` and ``postprocess.TIKZCD_INLINE_MAP``
(both populated by ``load_overrides``). Late-imported at call time
to avoid the circular import at module load (P3a).
"""

from __future__ import annotations

import html
import re

from conversion_context import current_context
from ._helpers import convert_label_colons
from .refs import routing_role, strip_doubled_noun_refs, strip_doubled_section_symbol


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


def convert_html_figures(text: str, ctx=None) -> str:
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
    ctx = ctx if ctx is not None else current_context()

    def make_admonition(label, caption):
        lines = ['```{admonition} Figure (TikZ — needs manual conversion)']
        if label:
            lines.append(f':name: {label}')
        lines.append('')
        lines.append(caption or '*(TikZ diagram — needs manual conversion)*')
        lines.append('```')
        return '\n'.join(lines)

    def _html_caption_to_myst(inner):
        """Process inner HTML caption-like content (from a
        ``<figcaption>`` body, or from a ``<div class="minipage">``
        sub-caption) into MyST-ready text. Pure on its input; reused for
        both extract paths."""
        cap = inner
        # Convert pandoc-resolved HTML ref anchors into MyST directives
        # BEFORE stripping HTML. The pre-resolved number in the ``<a>``
        # body is chapter-unaware (pandoc only sees the split-per-
        # chapter file, not the book), but the ``data-reference``
        # attribute preserves the original label — MyST can resolve it
        # with full project context (closes #33).
        #
        # Dispatch the directive type via ``routing_role`` so equation
        # refs become ``{eq}``, figure/table refs become ``{numref}``,
        # theorem-family refs become ``{prf:ref}`` — generic ``{ref}``
        # can't resolve to those anchor types in MyST (closes #38).
        def _replace_ref(m):
            raw = m.group(1)
            label = convert_label_colons(raw)
            return '{' + routing_role(raw) + '}`' + label + '`'
        cap = re.sub(
            r'<a[^>]*data-reference="([^"]+)"[^>]*>[^<]*</a>',
            _replace_ref,
            cap,
        )
        # Convert citation spans BEFORE stripping HTML (closes #89).
        # Pandoc emits ``\citet{X}`` / ``\citep{X}`` inside a caption as
        # an EMPTY ``<span class="citation" data-cites="X"></span>`` —
        # key in the attribute, no text content — so the generic tag-
        # strip below would drop both the span and the key. Rewrite to
        # pandoc native markdown (``@X`` or ``[@a; @b]``) here, and
        # ``convert_citations`` (later in ``process_text``) resolves to
        # ``{cite:t}`X```. NB: pandoc collapses ``\citet`` / ``\citep``
        # / ``\citep[loc]`` to the same empty-span form so all variants
        # land as textual — a small fidelity loss vs losing the key.
        def _replace_cite(m):
            keys = m.group(1).split()
            if len(keys) == 1:
                return '@' + keys[0]
            return '[' + '; '.join('@' + k for k in keys) + ']'
        cap = re.sub(
            r'<span\b[^>]*\bdata-cites="([^"]+)"[^>]*>[^<]*</span>',
            _replace_cite,
            cap,
        )
        cap = re.sub(r'<[^>]+>', '', cap).strip()
        # Pandoc HTML-encodes ``<`` / ``>`` / ``&`` inside figcaption
        # content. Inside prose the browser decodes them on render, but
        # inside ``$...$`` math regions KaTeX sees the entities as
        # literal chars and fails to parse (``$\mu+I&gt;0$`` → KaTeX
        # parse error). Unescape the whole caption: ``html.unescape``
        # is idempotent on plain text, source readability improves,
        # PDF builds that don't run an HTML decoder also work (closes
        # #40).
        cap = html.unescape(cap)
        # The doubled-noun strippers ran earlier in ``process_file``;
        # any ``§ Section`` / ``Chapter Chapter`` produced *here* by
        # the ref-conversion above would otherwise survive into the
        # final caption. Re-run them locally on the caption string.
        cap = strip_doubled_noun_refs(cap)
        cap = strip_doubled_section_symbol(cap)
        return cap

    def extract_caption(block):
        # NB: the regex deliberately does NOT skip leading inner tags
        # (the old form had a ``(?:<[^>]*>)*`` eater here). That eater
        # discards any attribute-bearing tag at the start of the
        # caption — e.g. a leading ``<span class="citation" ...>`` from
        # a caption that opens with ``\citet{X}`` — before
        # ``_html_caption_to_myst`` can recover the key. Capture the
        # full inner and let the helper handle all tag stripping /
        # attribute recovery.
        cap_match = re.search(
            r'<figcaption>\s*(.*?)\s*</figcaption>',
            block,
            re.DOTALL,
        )
        if not cap_match:
            return ''
        return _html_caption_to_myst(cap_match.group(1))

    def extract_minipage_subcaptions(block):
        """Gather ``<div class="minipage">…</div>`` content inside a
        figure as a list of sub-caption strings, in source order. Pandoc
        emits per-panel ``\\begin{minipage}`` text (sub-captions like
        ``{\\footnotesize (a) …}``) as these divs inside ``<figure>``;
        the figure-emit otherwise drops everything but ``<figcaption>``
        (closes #90)."""
        out = []
        for mp in re.finditer(
            r'<div class="minipage">(.*?)</div>', block, re.DOTALL
        ):
            text = _html_caption_to_myst(mp.group(1))
            if text:
                out.append(text)
        return out

    def _combine_caption(block, main_caption):
        """Fold any minipage sub-captions inside ``block`` in front of
        ``main_caption``, separated by blank lines. Source-order is the
        natural reading order (sub-cap (a), sub-cap (b), main caption).
        """
        subs = extract_minipage_subcaptions(block)
        return '\n\n'.join(t for t in (*subs, main_caption) if t)

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

        # Composite-override fast path (closes #49). If the outer
        # label has a ``TIKZ_FIGURE_MAP`` entry — meaning the
        # consumer has manually composed a single SVG/PDF that
        # represents all the subfigures together (xfig overlays,
        # combined TikZ output, etc.) — bypass per-subfigure splitting
        # entirely. The inner ``<embed>`` srcs may point at xfig-
        # rewritten paths that don't exist on disk; splitting would
        # produce ``{figure}`` directives with broken image refs.
        # Emit a single admonition placeholder for the outer label;
        # ``resolve_tikz_figures`` substitutes the composite from
        # ``ctx.tikz_figure_map``. The outer caption is preserved.
        if outer_label and outer_label in ctx.tikz_figure_map:
            outer_cap_raw = m.group('outer_cap')
            outer_caption = extract_caption(
                f'<figcaption>{outer_cap_raw}</figcaption>'
            )
            return make_admonition(outer_label, outer_caption)

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
        # ``_combine_caption`` folds any ``<div class="minipage">`` sub-
        # captions in source order ahead of the main figcaption (#90).
        caption = _combine_caption(block, extract_caption(block))
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


def resolve_tikz_figures(text: str, stem: str, ctx=None) -> str:
    """Replace TikZ admonition placeholders with actual figure directives.

    Also handles:
    - Stray HTML remnants from subfigure environments
    - Unlabeled TikZ admonition blocks (orphaned sub-panels)
    - Inline tikzcd math blocks → {image} directives
    """
    # Per-project TikZ maps live on the context (populated by load_overrides).
    ctx = ctx if ctx is not None else current_context()
    tikz_figure_map = ctx.tikz_figure_map
    tikzcd_inline_map = ctx.tikzcd_inline_map

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

            if label and label in tikz_figure_map:
                path, caption_override = tikz_figure_map[label]
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
    if stem in tikzcd_inline_map:
        for entry in tikzcd_inline_map[stem]:
            text = re.sub(
                entry['pattern'],
                lambda m, r=entry['replacement']: r,
                text,
                flags=re.DOTALL,
            )

    return text
