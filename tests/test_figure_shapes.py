"""Shape catalogue: figure forms × caption variants.

Sibling-parity guard for the figure-handling family. Issues #21 /
#25 / #31 / #33 / #35 all surfaced shape-specific bugs: pandoc emits
multiple distinct shapes for what looks the same semantic figure,
and the transform suite must handle each consistently.

Three shapes pandoc emits:

1. **Markdown image** — ``![cap](path){#id}`` from plain
   ``\\includegraphics{path}``. Handled by ``convert_figures``.
2. **HTML figure** — ``<figure id="..."><img/><figcaption>...``.
   Emitted for TikZ-shaped placeholders and some embed forms.
   Handled by ``convert_html_figures``.
3. **HTML nested subfigure** — outer figure wrapping multiple inner
   ones. The dominant subfigure-package shape. Handled by the same
   pass with separate nesting logic.

Caption variants worth covering:

- ``no_caption`` — plain image, no caption.
- ``plain_caption`` — ASCII caption, no special chars.
- ``caption_with_ref`` — pandoc-resolved ``\\ref{}`` inside the
  caption (#33).
- ``caption_with_brace_macros`` — caption containing ``\\texttt{X}``
  etc. (#35 was the lstlisting variant; figures are usually fine
  but the test covers the analogous shape).
"""

from __future__ import annotations

import re

import pytest

import postprocess


# ── Markdown-image shape: ![cap](path){#id} ─────────────────────────────────


@pytest.mark.parametrize("caption,expected_in_caption", [
    ('Plain caption.',                'Plain caption.'),
    ('Caption with \\texttt{Pi}.',    'Caption with \\texttt{Pi}.'),
])
def test_markdown_figure_with_label_and_caption(caption: str, expected_in_caption: str):
    """``![cap []{#fig:foo}](path)`` → ``{figure}`` directive with
    ``:name:`` set."""
    src = f'![{caption} []{{#fig:foo}}](myfig.png)\n'
    out = postprocess.convert_figures(src)
    assert '```{figure}' in out
    assert ':name: fig-foo' in out
    assert expected_in_caption in out


def test_markdown_figure_no_label_no_name_option():
    """An unlabelled markdown image becomes a figure with no
    ``:name:`` (still renders, just not cross-refable)."""
    src = '![Just a caption.](path.png)\n'
    out = postprocess.convert_figures(src)
    assert '```{figure}' in out
    assert ':name:' not in out


# ── HTML figure shape: <figure id="..."><img/><figcaption/></figure> ────────


HTML_BASE = (
    '<figure id="fig:bar">\n'
    '<img src="bar.png" />\n'
    '<figcaption>{caption}</figcaption>\n'
    '</figure>\n'
)


@pytest.mark.parametrize("caption,expected_in_caption", [
    ('Plain caption.',                            'Plain caption.'),
    ('Caption with <em>emphasis</em>.',           'Caption with emphasis.'),
    ('Caption with \\texttt{Pi}.',                'Caption with \\texttt{Pi}.'),
])
def test_html_figure_with_plain_caption(caption: str, expected_in_caption: str):
    """HTML figure with various non-ref caption shapes. Caption text
    must survive into the MyST ``{figure}`` body."""
    src = HTML_BASE.replace('{caption}', caption)
    out = postprocess.convert_html_figures(src)
    assert '```{figure}' in out
    assert ':name: fig-bar' in out
    assert expected_in_caption in out


def test_html_figure_caption_with_section_ref_becomes_myst_ref():
    """GH #33 — pandoc-resolved ``\\ref{sec:X}`` inside the caption
    arrives as ``<a data-reference="sec:X">N</a>``. Must become a
    MyST ``{ref}`` directive, not have the wrong baked number
    stripped to plain text."""
    src = HTML_BASE.replace(
        '{caption}',
        'The bilevel search of §<a href="#sec:foo" '
        'data-reference-type="ref" data-reference="sec:foo">2</a> '
        'is end-to-end feasible.'
    )
    out = postprocess.convert_html_figures(src)
    assert '{ref}`sec-foo`' in out
    # The pre-resolved number must not leak as literal text.
    assert '§2' not in out
    assert '§ 2' not in out


@pytest.mark.parametrize("target_label,expected_role", [
    ('eq:foo',         'eq'),         # equation → {eq}
    ('fig:bar',        'numref'),     # figure   → {numref}
    ('tab:loss',       'numref'),     # table    → {numref}
    ('thm:main',       'prf:ref'),    # theorem  → {prf:ref}
    ('alg:young',      'prf:ref'),    # algorithm
    ('lem:contraction','prf:ref'),    # lemma
    ('sec:intro',      'ref'),        # section  → {ref}
    ('ch:climate',     'ref'),        # chapter
])
def test_html_figure_caption_ref_dispatches_by_target_type(target_label, expected_role):
    """GH #38 — captions cross-referencing typed targets (equations,
    figures, theorems, algorithms) need typed directives. Generic
    ``{ref}`` cannot resolve to a trailing-paren ``$$ (eq-X)`` anchor
    or a ``{prf:theorem}`` directive. Route by label prefix via
    ``routing_role`` (single source of truth in
    ``transforms.refs``)."""
    src = HTML_BASE.replace(
        '{caption}',
        f'See <a href="#{target_label}" data-reference-type="ref" '
        f'data-reference="{target_label}">N</a> below.'
    )
    out = postprocess.convert_html_figures(src)
    label_kebab = target_label.replace(':', '-')
    expected_directive = '{' + expected_role + '}`' + label_kebab + '`'
    assert expected_directive in out, (
        f'caption ref to {target_label!r} should produce {expected_directive!r}\n'
        f'  actual output:\n{out}'
    )
    # Pre-resolved ``N`` text must not leak.
    assert '>N</a>' not in out


# ── #40 — HTML entities inside caption ───────────────────────────────────────


def test_caption_unescapes_html_entities_inside_math():
    """GH #40 — pandoc HTML-encodes ``<`` / ``>`` / ``&`` in figcaption
    content (``$\\mu+I&gt;0$``). Inside prose the browser decodes them;
    inside ``$...$`` KaTeX sees the entities as literal chars and
    fails to parse. Unescape the whole caption (``html.unescape`` is
    idempotent)."""
    src = HTML_BASE.replace(
        '{caption}',
        'For positive ($\\mu+I&gt;\\sqrt{\\mu^2+I^2}$).'
    )
    out = postprocess.convert_html_figures(src)
    assert '$\\mu+I>\\sqrt{\\mu^2+I^2}$' in out
    assert '&gt;' not in out


def test_caption_unescapes_html_entities_in_prose_too():
    """The whole caption is unescaped (not just math regions) so
    source readability is preserved and PDF builds that don't decode
    HTML entities also work."""
    src = HTML_BASE.replace(
        '{caption}',
        'When I &gt; 0 and $x &lt; y$, then $A &amp; B$.'
    )
    out = postprocess.convert_html_figures(src)
    assert 'I > 0' in out
    assert '$x < y$' in out
    assert '$A & B$' in out
    assert '&gt;' not in out and '&lt;' not in out and '&amp;' not in out


def test_caption_unescape_is_idempotent_on_plain_text():
    """A caption that never had entities round-trips unchanged
    through ``html.unescape``."""
    src = HTML_BASE.replace(
        '{caption}',
        'Plain caption with $x > 0$ already literal.'
    )
    out = postprocess.convert_html_figures(src)
    assert 'Plain caption with $x > 0$ already literal.' in out


# ── HTML nested subfigure shape ─────────────────────────────────────────────


def _nested(outer_label: str, inner_labels: list[str],
            outer_caption: str = 'Outer.',
            inner_captions: list[str] | None = None) -> str:
    """Build a nested-subfigure pandoc snippet."""
    if inner_captions is None:
        inner_captions = [f'Inner {i}.' for i in range(len(inner_labels))]
    inner_blocks = ''.join(
        f'<figure id="{lbl}">\n<img src="{lbl}.png" />\n'
        f'<figcaption>{cap}</figcaption>\n</figure>\n'
        for lbl, cap in zip(inner_labels, inner_captions)
    )
    return (
        f'<figure id="{outer_label}">\n'
        f'{inner_blocks}'
        f'<figcaption>{outer_caption}</figcaption>\n'
        f'</figure>\n'
    )


def test_nested_two_labelled_subfigures():
    """Two labelled subfigures inside an unreferenced parent. Each
    inner keeps its own label and emits its own ``{figure}``."""
    src = _nested('fig:panels', ['fig:a', 'fig:b'])
    # Parent NOT referenced anywhere → both inner labels survive.
    out = postprocess.convert_html_figures(src)
    assert out.count('```{figure}') == 2
    assert ':name: fig-a' in out
    assert ':name: fig-b' in out


def test_nested_referenced_outer_takes_first_child_slot():
    """When the parent label IS referenced, issue #21 / lesson 021
    moves it onto the first child's ``:name:`` so the parent reference
    resolves. Second child keeps its own label."""
    src = _nested('fig:panels', ['fig:a', 'fig:b'])
    src += '\nSee {numref}`fig-panels`.\n'
    out = postprocess.convert_html_figures(src)
    assert ':name: fig-panels' in out
    assert ':name: fig-b' in out
    # First child's own label is sacrificed to make the parent ref
    # resolve — documented behaviour, not a bug.


def test_nested_inner_caption_with_html_emphasis():
    """Inner caption with HTML markup strips to plain text."""
    src = _nested('fig:panels', ['fig:a'],
                  inner_captions=['Panel <em>A</em>.'])
    out = postprocess.convert_html_figures(src)
    assert 'Panel A.' in out
    assert '<em>' not in out


def test_nested_composite_override_emits_single_admonition(monkeypatch):
    """#49 fix: when the outer label has a ``TIKZ_FIGURE_MAP`` entry,
    nested subfigures collapse to a SINGLE admonition placeholder
    for the outer label — bypassing per-subfigure split.

    Surfaced by book-dp1's ``ch_val.tex`` ``f-du`` figure: outer
    label was in the map (composite SVG), but the inner
    ``\\includegraphics`` refs (rewritten from xfig ``.pdf_t``
    overlays) pointed at PDFs that don't exist on disk. The pre-fix
    behaviour emitted two ``{figure}`` directives with broken image
    refs AND dropped the outer caption.

    The fix: check TIKZ_FIGURE_MAP BEFORE entering the
    per-subfigure split loop. If outer label is present, emit a
    single admonition (with the outer caption); resolve_tikz_figures
    will substitute the composite later."""
    monkeypatch.setattr(
        postprocess, 'TIKZ_FIGURE_MAP', {'f-du': ('figures/du.svg', None)},
    )
    src = _nested('f:du', ['f:du-a', 'f:du-b'],
                  outer_caption="Du's theorem: convex and concave cases",
                  inner_captions=['', ''])
    out = postprocess.convert_html_figures(src)

    # ONE admonition placeholder, not two figure directives.
    assert out.count('```{admonition}') == 1
    assert '```{figure}' not in out

    # Outer label is on the admonition; child labels are NOT.
    assert ':name: f-du' in out
    assert ':name: f-du-a' not in out
    assert ':name: f-du-b' not in out

    # Outer caption is preserved (was dropped pre-fix).
    assert "Du's theorem: convex and concave cases" in out


def test_nested_no_composite_override_falls_back_to_per_subfigure(monkeypatch):
    """Regression guard: when the outer label is NOT in
    ``TIKZ_FIGURE_MAP``, the existing per-subfigure-split behaviour
    is preserved. The composite-override path is a strict
    refinement, not a replacement."""
    monkeypatch.setattr(postprocess, 'TIKZ_FIGURE_MAP', {})
    src = _nested('fig:panels', ['fig:a', 'fig:b'])
    out = postprocess.convert_html_figures(src)
    # Existing two-figure split behaviour.
    assert out.count('```{figure}') == 2
    assert ':name: fig-a' in out
    assert ':name: fig-b' in out


def test_nested_composite_override_outer_caption_with_ref_resolves(monkeypatch):
    """The outer caption may contain pandoc-resolved ``<a>`` ref
    anchors (``\\ref{}`` resolves to an HTML link with
    ``data-reference``). The composite-override path runs the
    caption through ``extract_caption`` so refs become MyST
    directives — same processing as the per-subfigure path."""
    monkeypatch.setattr(
        postprocess, 'TIKZ_FIGURE_MAP', {'f-x': ('figures/x.svg', None)},
    )
    src = _nested(
        'f:x', ['f:a'],
        outer_caption=(
            'See <a data-reference-type="ref" data-reference="ch:bar">'
            'Chapter 2</a> for context.'
        ),
        inner_captions=[''],
    )
    out = postprocess.convert_html_figures(src)
    # Ref resolves to MyST directive (specific role depends on the
    # routing table; assert the curly-brace directive form).
    assert '<a ' not in out, f'raw <a> tag leaked: {out!r}'
    assert 'data-reference' not in out
    assert '`ch-bar`' in out
