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


def hoist_consecutive_heading_labels(text: str) -> str:
    """Stack a heading's *secondary* ``\\label{}``s above the heading.

    LaTeX allows several consecutive labels on one sectioning command::

        \\subsection{The MDP Model}\\label{ss:gfsmdp}\\label{sss:fsmdp}

    Pandoc folds only the **first** label into the heading id and emits the
    rest as leading ``[]{#…}`` spans on the *following* paragraph::

        (ss-gfsmdp)=
        ## The MDP Model

        []{#sss:fsmdp label="sss:fsmdp"} We study a controller …

    Left alone, ``convert_standalone_labels`` strips that mid-line orphan, so
    a ``{ref}`sss-fsmdp``` resolves to the paragraph node (no section number)
    and mystmd renders the generic node name "Paragraph" (issue #108). This
    transform pulls the leading anchor spans off the first post-heading
    paragraph and stacks them — in author order, after the heading's own
    ``(primary)=`` line — so every label resolves to the heading's number::

        (ss-gfsmdp)=
        (sss-fsmdp)=
        ## The MDP Model

        We study a controller …

    Runs **after** ``convert_section_labels`` (heading id already a
    ``(primary)=`` anchor) and **before** ``convert_standalone_labels`` (so
    the orphan span is still present, not yet stripped). Only leading spans on
    the *first* non-blank line after the heading are hoisted, so a genuine
    own-line anchor further down (or a footnote orphan mid-paragraph) is left
    for the existing strip path.
    """
    anchor_re = re.compile(r'^\(([^)]+)\)=\s*$')
    heading_re = re.compile(r'^#{1,6}\s+\S')
    # A run of one or more leading ``[]{#label}`` spans, then the rest.
    lead_re = re.compile(
        r'^((?:\[\]\{#[^\s}]+(?:\s+label="[^"]*")?\}[ \t]*)+)(.*)$'
    )
    span_re = re.compile(r'\[\]\{#([^\s}]+)(?:\s+label="[^"]*")?\}')

    lines = text.split('\n')
    out: list[str] = []
    i = 0
    n = len(lines)
    while i < n:
        # A contiguous block of ``(x)=`` anchors immediately above a heading.
        if anchor_re.match(lines[i]):
            k = i
            while k < n and anchor_re.match(lines[k]):
                k += 1
            if k < n and heading_re.match(lines[k]):
                anchor_block = lines[i:k]
                heading = lines[k]
                # First non-blank line after the heading.
                p = k + 1
                while p < n and lines[p].strip() == '':
                    p += 1
                secondary: list[str] = []
                if p < n and not heading_re.match(lines[p]):
                    lm = lead_re.match(lines[p])
                    if lm:
                        secondary = [
                            f'({convert_label_colons(s)})='
                            for s in span_re.findall(lm.group(1))
                        ]
                        remainder = lm.group(2).lstrip()
                        if remainder:
                            lines[p] = remainder
                        else:
                            # Anchors were the whole line — drop it so we
                            # don't leave a stray blank inside the paragraph.
                            del lines[p]
                            n -= 1
                if secondary:
                    out.extend(anchor_block)
                    out.extend(secondary)
                    out.append(heading)
                    i = k + 1
                    continue
        out.append(lines[i])
        i += 1
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
        bare_h1 = re.match(r'#\s+' + re.escape(title) + r'\s*\n+', text)
        if bare_h1:
            text = text[bare_h1.end():]
    frontmatter = f'---\ntitle: "{title}"\n'
    if label:
        frontmatter += f'label: {label}\n'
    frontmatter += '---\n\n'
    return frontmatter + text
