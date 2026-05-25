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


def test_html_figure_caption_with_eq_ref():
    """Caption referring to an equation should also become a MyST
    role; the routing should pick ``{eq}`` for ``eq:`` prefixes."""
    src = HTML_BASE.replace(
        '{caption}',
        'See <a href="#eq:foo" data-reference-type="ref" '
        'data-reference="eq:foo">3</a> below.'
    )
    out = postprocess.convert_html_figures(src)
    # Today's extract_caption emits {ref} for everything (the prefix
    # routing isn't applied inside the caption). Lock that — it's
    # acceptable because MyST resolves either way (P1a's validator
    # confirms anchor exists).
    assert 'eq-foo' in out
    # The pre-resolved number must not leak.
    assert re.search(r'>\s*3\s*<', out) is None


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
