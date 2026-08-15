"""Frontmatter, section-label, and post-rewrites transforms.

``add_frontmatter`` emits either the YAML-block ``absorbed`` style
(dp2 default) or the ``(label)= / # Title`` ``standalone`` style
(dp1) at the top of each chapter. ``convert_section_labels`` and
``convert_standalone_labels`` handle the body-side label promotions
that produce the anchors the YAML block draws on.

``apply_postprocess_rewrites`` runs book-specific markdown rewrites
from ``config.postprocess.rewrites`` after everything else.

State coupling: ``_FRONTMATTER_STYLE`` and ``POSTPROCESS_REWRITES``
live on ``postprocess`` (populated by ``apply_config``); late-imported
at call time.
"""

from __future__ import annotations

import re

from conversion_context import current_context
from ._helpers import convert_label_colons


def _pandoc_auto_id(title: str) -> str:
    """Re-derive pandoc's ``auto_identifiers`` slug from a converted heading
    title, or ``''`` when it can't be determined (#194).

    Pandoc's documented algorithm, applied to the heading's stringified
    inlines: strip formatting and footnotes → remove every character except
    alphanumerics, ``_``, ``-``, ``.`` and spaces → spaces to hyphens →
    lowercase → drop everything up to the first letter.

    We run it against the *markdown* title rather than the original LaTeX,
    so the reconstruction is approximate: a title carrying a footnote
    reference, a non-ASCII letter, or markdown the character filter can't
    reduce the same way will not round-trip. **Every such mismatch is
    fail-safe** — the caller only ever uses equality to *suppress* an
    anchor, so a bad reconstruction keeps the anchor and reproduces the
    pre-#194 behaviour rather than dropping a live target.
    """
    # Links: pandoc stringifies to the label text, not the destination.
    t = re.sub(r'\[([^\]]*)\]\([^)]*\)', r'\1', title)
    # Keep alphanumerics (``\w`` also covers ``_``), period, hyphen, space.
    # This also disposes of the ``*``/``` ` ```/``$`` markdown carries —
    # pandoc never saw them, and they are non-alphanumeric either way.
    t = re.sub(r'[^\w.\- ]', '', t, flags=re.UNICODE)
    t = re.sub(r'\s+', '-', t.strip())
    t = t.lower()
    return re.sub(r'^[^a-z]+', '', t)


def convert_section_labels(text: str) -> str:
    """Convert pandoc section header IDs to MyST label syntax.

    # Title {#sec:label} → (sec-label)=\\n# Title

    Pandoc may append class/property tokens after the slug for unnumbered
    or unlisted headings (``{#slug .unnumbered .unlisted}``). Only the first
    whitespace-delimited token of the attribute block (``slug`` — the regex
    captures from after the ``{#``, so the token carries no leading ``#``)
    is treated as the identifier.

    **``.unnumbered`` is re-emitted (#160A).** A *starred* sectioning
    command (``\\section*``) is unnumbered in LaTeX, and pandoc records that
    as a ``.unnumbered`` class. Discarding it made book-mode numbering
    number the heading anyway — a "Summary" section taking §1.5 and pushing
    the next section to §1.6, against the printed book. From ``qe-v10`` the
    renderer parses a pandoc-style attribute block on a heading, so the
    class is re-emitted as a bare ``{.unnumbered}`` block, which it reads as
    ``enumerated: false``: the heading renders with no number *and does not
    advance the counter*, which is exactly ``\\section*`` semantics. It
    keeps its target and TOC entry, so cross-references still resolve (they
    render the section *title* rather than a number — the only honest
    rendering, since a starred section has no number to show).

    **This needs the ``qe-v10`` renderer floor.** On ``qe-v9`` and earlier
    there is no heading-attribute parser, so the block would render as
    literal ``{.unnumbered}`` text in the title *and* pollute the derived
    slug. Unlike the ``qe-v9`` coupling from #186, this one is not
    forgiving — an older renderer corrupts the page rather than silently
    forfeiting the fix.

    Only ``.unnumbered`` is re-emitted; any other class pandoc attached is
    dropped as before. Not for safety — the renderer accepts an unknown
    class and simply carries it as an inert ``class`` attribute — but
    because nothing downstream gives one meaning, and pandoc attaches
    nothing else here anyway (measured across all three books: the block is
    always exactly ``{#slug}`` or ``{#slug .unnumbered}``). What the parser
    *does* reject is a token of an unrecognized **kind** (``{foo=bar}``,
    ``{not-a-class}``), and then it abandons the whole block and leaves the
    braces as literal text — which is why the emitted block is assembled
    from a fixed vocabulary rather than passed through from pandoc.

    **Derived slugs are not promoted (#194).** Pandoc's ``auto_identifiers``
    mints an id for every heading, whether or not the author wrote a
    ``\\label{}``, and normally omits the attribute block when it can
    re-derive that id itself — but a *starred* sectioning command forces an
    attribute block (for ``.unnumbered``) that drags the derived id along.
    Promoting those to ``(slug)=`` makes an anchor out of a section title,
    and two chapters with a "Further reading" section then collide
    project-wide ("Duplicate identifier in project"). So an anchor is
    suppressed when the slug is exactly what pandoc would derive from the
    title — the case where mystmd's ``headingLabelTransform`` mints an
    *implicit* identifier with the same string, making the anchor redundant
    (implicit headings are also exempt from the duplicate-identifier
    warning, which is what clears the collisions).

    Two guards keep this from eating real targets:

    - **Author labels can't match.** A ``\\label{sec:foo}`` reaches us as
      ``sec:foo``, and ``_pandoc_auto_id`` never emits a colon, so the whole
      ``sec:``/``ss:``/``c:`` labelling convention is protected by the
      equality test alone. A label that *does* coincide with its title slug
      is indistinguishable from a derived one — and dropping it is
      harmless, because the implicit identifier is that same string.
    - **Depth 1 is never suppressed.** ``add_frontmatter`` keys on the
      ``(label)=`` + ``# Title`` pair to build a page's ``label:``
      (``absorbed``) or to detect that the body already has its heading
      (``standalone``). Suppressing an H1 anchor therefore drops the page
      target in one style and emits a *duplicate* H1 in the other. H1 slugs
      are per-file chapter titles and don't collide anyway, so the gate is
      free.

    Pandoc's within-file dedup suffixes (``optimality-1``) are deliberately
    left alone: they are unique by construction, so they never produce the
    warning this addresses, and suppressing one is *not* identifier-neutral
    (mystmd would mint ``optimality``, a different string).
    """
    def replace_header(m):
        hashes = m.group(1)
        title = m.group(2).strip()
        attrs = m.group(3).split()
        slug = attrs[0]
        # Re-emit the numbering channel, drop every other class (#160A).
        suffix = ' {.unnumbered}' if '.unnumbered' in attrs[1:] else ''
        derived = _pandoc_auto_id(title)
        if len(hashes) >= 2 and derived and slug == derived:
            # The id is redundant with the implicit one mystmd mints from
            # the title, so the anchor goes — but the heading still has to
            # carry its numbering class.
            return f'{hashes} {title}{suffix}'
        label = convert_label_colons(slug)
        return f'({label})=\n{hashes} {title}{suffix}'

    text = re.sub(
        r'^(#{1,6})\s+(.+?)\s+\{#([^}]+)\}\s*$',
        replace_header,
        text,
        flags=re.MULTILINE
    )

    return text


def hoist_consecutive_heading_labels(text: str, ctx=None) -> str:
    """Consume a heading's *secondary* ``\\label{}`` orphan spans (#108).

    LaTeX allows several consecutive labels on one sectioning command::

        \\subsection{The MDP Model}\\label{ss:gfsmdp}\\label{sss:fsmdp}

    Pandoc folds only the **first** label into the heading id and emits the
    rest as leading ``[]{#…}`` spans on the *following* paragraph. Neither
    naive treatment works in a real mystmd build:

    - leaving the span (pre-#114): it resolves to the paragraph node and a
      ``{ref}`` renders the generic node name "Paragraph";
    - stacking it as a second ``(name)=`` anchor above the heading (the
      first #114 attempt): mystmd keeps only ONE anchor per heading —
      "label X replaced with Y" — and refs to the dropped one dangle
      (verified against myst v1.9.1 in the dp1 build test).

    The working design is **alias-rewriting**: ``ctx.heading_label_aliases``
    (scanned from the sources at config time) maps each secondary label to
    its primary, ``convert_cross_references`` rewrites every ref to the
    primary (so it renders the true section number), and this transform's
    only job is to *consume* the now-targetless orphan spans so they don't
    leak. Only spans whose label is in the alias map are touched — anything
    else (footnote orphans, genuine own-line anchors) is left for the
    existing paths.
    """
    ctx = ctx if ctx is not None else current_context()
    aliases = ctx.heading_label_aliases
    if not aliases or '[]{#' not in text:
        return text

    lead_re = re.compile(
        r'^(?:\[\]\{#[^\s}]+(?:\s+label="[^"]*")?\}[ \t]*)+'
    )
    span_re = re.compile(r'(\[\]\{#([^\s}]+)(?:\s+label="[^"]*")?\}[ \t]*)')

    out: list[str] = []
    for line in text.split('\n'):
        if not lead_re.match(line):
            out.append(line)
            continue
        rebuilt = line
        changed = False
        for whole, label in span_re.findall(line):
            if convert_label_colons(label) in aliases:
                rebuilt = rebuilt.replace(whole, '', 1)
                changed = True
        if not changed:
            out.append(line)
        elif rebuilt.strip():
            out.append(rebuilt.lstrip())
        # else: the line was nothing but consumed spans — drop it entirely
        # (no stray blank inside the paragraph).
    return '\n'.join(out)


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


def apply_postprocess_rewrites(text: str, stem: str, ctx=None) -> str:
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
    ctx = ctx if ctx is not None else current_context()
    for pattern, replacement, stems in ctx.postprocess_rewrites:
        if stems is not None and stem not in stems:
            continue
        text = pattern.sub(replacement, text)
    return text


def add_frontmatter(text: str, title: str, style: str | None = None, ctx=None) -> str:
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

    ``style`` overrides ``ctx.frontmatter_style`` for this one call — used
    by ``process_file`` to honour per-chapter overrides declared in
    ``config.chapters[].frontmatter_style`` or
    ``config.extra_files[].frontmatter_style``.

    Idempotent: re-processing a file already in either style is a no-op
    (modulo title updates from config). Existing YAML ``label:`` values
    are preserved so chapter cross-references like ``{prf:ref}`c-egs```
    keep resolving even if the LaTeX source no longer carries the label.
    """
    ctx = ctx if ctx is not None else current_context()
    effective_style = style if style is not None else ctx.frontmatter_style
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
        #
        # The trailing block is optional because an H1 can now carry one
        # (``# Preface {.unnumbered}``, #160A). Nothing reaches this line
        # with a block today — ``convert_section_labels`` never suppresses a
        # depth-1 anchor, so such a heading always arrives as the
        # ``(label)=`` pair matched above — but the title-equality test
        # would otherwise fail on the braces alone and resurrect #3.
        #
        # Matched literally, not as ``\{[^}]*\}``: this branch *deletes* the
        # heading on a match, so a permissive group would make
        # ``# Preface {see note}`` read as the title ``Preface`` and drop a
        # heading the author wrote. Only the exact block we emit is absorbed.
        bare_h1 = re.match(
            r'#\s+' + re.escape(title) + r'(?:[ \t]+\{\.unnumbered\})?\s*\n+',
            text,
        )
        if bare_h1:
            text = text[bare_h1.end():]
    frontmatter = f'---\ntitle: "{title}"\n'
    if label:
        frontmatter += f'label: {label}\n'
    frontmatter += '---\n\n'
    return frontmatter + text
