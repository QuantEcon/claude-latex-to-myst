"""Tests for the figure-marker preprocessor + resolver (Phase 1).

Closes #89/#90/#92/#93. Mirrors the test structure used for the table-
marker pipeline (#51/#55). Sections:

1. Pre-pandoc parser (``parse_figure_block`` + ``find_figure_blocks``).
2. Marker encode/decode round-trip.
3. Post-pandoc resolver (``resolve_figure_markers``).
4. End-to-end: preprocessor → pandoc → resolver → postprocess chain.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

# Make the scripts/ dir importable.
SCRIPTS = Path(__file__).resolve().parent.parent / 'scripts'
sys.path.insert(0, str(SCRIPTS))

import _apply_figure_markers as pre  # noqa: E402
from transforms.figures_from_latex import (  # noqa: E402
    FigureSpec,
    decode_marker,
    encode_marker,
    find_figure_blocks,
    parse_figure_block,
    resolve_figure_markers,
)
from transforms.cite import convert_citations, decode_natbib_markers  # noqa: E402


PANDOC_AVAILABLE = shutil.which('pandoc') is not None


# ── 1. Pre-pandoc parser ────────────────────────────────────────────────────


def test_parse_simple_figure_extracts_label_caption_image():
    """The canonical shape: a ``\\begin{figure}`` with one
    ``\\includegraphics``, one ``\\caption{}`` and one ``\\label{}``."""
    body = (
        '\\centering\n'
        '\\includegraphics{plot.pdf}\n'
        '\\caption{A plot.}\n'
        '\\label{fig:plot}\n'
    )
    spec = parse_figure_block(body, placement='ht')
    assert spec is not None
    assert spec.name == 'fig-plot'                 # colon → hyphen
    assert spec.caption == 'A plot.'
    assert spec.image_src == 'plot.pdf'
    assert spec.width is None                      # no [width=…] option
    assert spec.tikz_input is None
    assert spec.sub_captions == []
    assert spec.placement == 'ht'


def test_parse_balanced_braces_in_caption():
    """Caption containing balanced braces (e.g. ``\\textbf{X}``) must
    be extracted intact — the brace-matcher is critical for citations
    and inline LaTeX in captions."""
    body = (
        '\\includegraphics{x.pdf}\n'
        '\\caption{Some \\textbf{bold} text and \\citet{X} too.}\n'
        '\\label{fig:bb}\n'
    )
    spec = parse_figure_block(body, placement=None)
    assert spec is not None
    assert spec.caption == 'Some \\textbf{bold} text and \\citet{X} too.'


def test_parse_subfigure_includegraphics_panels():
    """#94 (Phase 4): a subfigure float whose every panel is a plain
    ``\\includegraphics`` is fully modelled — parse one panel spec per
    subfigure, with the outer label captured on the spec."""
    body = (
        '\\begin{subfigure}{0.5\\textwidth}\n'
        '\\includegraphics{a.pdf}\n'
        '\\caption{Panel A}\n'
        '\\end{subfigure}\n'
        '\\begin{subfigure}{0.5\\textwidth}\n'
        '\\includegraphics{b.pdf}\n'
        '\\caption{Panel B}\n'
        '\\end{subfigure}\n'
        '\\caption{\\label{f:outer} Outer.}\n'
    )
    spec = parse_figure_block(body, placement=None)
    assert spec is not None
    assert spec.name == 'f-outer'
    assert [s['image_src'] for s in spec.subfigures] == ['a.pdf', 'b.pdf']
    assert spec.image_src is None  # the float itself carries no single image


def test_parse_bails_on_scalebox_input_subfigure():
    """#94 conservatism: a subfigure panel that is NOT a plain
    ``\\includegraphics`` (dp1's ``\\scalebox{\\input{…pdf_t}}``) can't be
    modelled, so the whole float bails to ``convert_html_figures``."""
    body = (
        '\\begin{subfigure}[t]{0.4\\textwidth}\n'
        '\\scalebox{0.45}{\\input{../figures/du_concave.pdf_t}}\n'
        '\\caption{}\n'
        '\\end{subfigure}\n'
        '\\caption{\\label{f:du} Du.}\n'
    )
    assert parse_figure_block(body, placement=None) is None


def test_parse_tikzpicture_caption_only_no_node_scoop():
    """#98 #3 + Phase 6: a ``\\begin{figure}`` wrapping a raw
    ``\\begin{tikzpicture}`` is now marker-ized **caption-only** — the tikz
    body (and its ``{\\footnotesize …}`` node labels, e.g. ``$a_3$``) is
    stripped BEFORE caption/label extraction, so node text is never scooped
    (the #98 #3 protection), but the figure caption + label are carried so
    their math survives. The image still comes from the post-pandoc
    ``TIKZ_FIGURE_MAP`` override (``_emit_figure`` does the lookup)."""
    body = (
        '\\begin{tikzpicture}[scale=1]\n'
        '\\node {\\footnotesize $a_3$};\n'
        '\\end{tikzpicture}\n'
        '\\caption{\\label{f:coase_no} Notation}\n'
    )
    spec = parse_figure_block(body, placement=None)
    assert spec is not None
    assert spec.name == 'f-coase_no'
    assert spec.caption == 'Notation'
    assert spec.image_src is None and spec.tikz_input is None
    # Critical (#98 #3): the tikz node text was NOT scooped.
    assert spec.sub_captions == []
    assert 'a_3' not in (spec.caption or '')


def test_parse_tikzpicture_inside_minipage_recovers_subcaptions():
    """The minipage-wrapped sub-panel shape: the tikz body is stripped (so
    tikz NODE labels are not scooped — #98 #3), but a legitimate
    ``{\\footnotesize (a) …}`` panel caption that sits OUTSIDE the tikzpicture
    is recovered as a sub-caption (DL multi-panel figures). The float
    ``\\caption`` + ``\\label`` are carried too."""
    body = (
        '\\begin{minipage}{0.4\\textwidth}\n'
        '\\begin{tikzpicture}\\end{tikzpicture}\\\\\n'
        '{\\footnotesize (a) the unit ball}\n'
        '\\end{minipage}\n'
        '\\caption{Main.}\n'
        '\\label{fig:vp}\n'
    )
    spec = parse_figure_block(body, placement=None)
    assert spec is not None
    assert spec.name == 'fig-vp'
    assert spec.caption == 'Main.'
    assert spec.sub_captions == ['(a) the unit ball']
    assert 'unit ball' not in (spec.caption or '')


def test_parse_footnotesize_subcaption_on_non_tikz_figure():
    """``_extract_footnotesize_subcaptions`` is still live for figures with
    NO ``\\begin{tikzpicture}`` — e.g. an ``\\includegraphics`` panel with a
    ``{\\footnotesize}`` note. Only the tikz case bails (above)."""
    body = (
        '\\includegraphics{panel.pdf}\\\\\n'
        '{\\footnotesize (a) the unit ball}\n'
        '\\caption{Main.}\n'
        '\\label{fig:vp}\n'
    )
    spec = parse_figure_block(body, placement=None)
    assert spec is not None
    assert spec.image_src == 'panel.pdf'
    assert spec.sub_captions == ['(a) the unit ball']


def test_parse_tikz_input_captured():
    """``\\input{tikz/foo}`` → ``tikz_input='foo'``. The marker resolver
    emits the same admonition placeholder shape ``convert_html_figures``
    used, so ``resolve_tikz_figures`` still substitutes via
    ``TIKZ_FIGURE_MAP``."""
    body = '\\input{tikz/diagram.tex}\n\\caption{X.}\n\\label{fig:t}\n'
    spec = parse_figure_block(body, placement=None)
    assert spec is not None
    assert spec.tikz_input == 'diagram'
    assert spec.image_src is None


def test_find_figure_blocks_in_source_order():
    """``find_figure_blocks`` returns blocks left-to-right (source
    order). Mirrors ``find_table_blocks``."""
    text = (
        'before\n'
        '\\begin{figure}\\includegraphics{a.pdf}\\caption{A.}\\label{fig:a}\\end{figure}\n'
        'middle\n'
        '\\begin{figure}[ht]\\includegraphics{b.pdf}\\caption{B.}\\label{fig:b}\\end{figure}\n'
        'after\n'
    )
    blocks = find_figure_blocks(text)
    assert len(blocks) == 2
    # First block: no placement
    assert blocks[0][3] is None
    # Second block: ht
    assert blocks[1][3] == 'ht'


# ── 1b. #98 regression locks: width / label-in-caption / path-on-next-line ──


def test_parse_width_textwidth_fraction_to_percent():
    """#98 #1: ``\\includegraphics[width=0.95\\textwidth]`` → ``95%``,
    matching pandoc's LaTeX→Markdown conversion that the old
    ``convert_figures`` path relied on. The marker path bypasses pandoc
    for the figure body, so the conversion happens in the parser."""
    body = (
        '\\includegraphics[width=0.95\\textwidth]{plot.pdf}\n'
        '\\caption{C.}\n\\label{fig:w}\n'
    )
    spec = parse_figure_block(body, placement=None)
    assert spec is not None
    assert spec.width == '95%'


def test_parse_width_various_fractions_and_units():
    """Fraction × {text,line,column,paper}width → percent; bare
    ``\\textwidth`` → ``100%``; absolute units pass through verbatim."""
    cases = {
        '[width=0.8\\textwidth]': '80%',
        '[width=0.55\\linewidth]': '55%',
        '[width=\\textwidth]': '100%',
        '[width=\\linewidth]': '100%',
        '[height=3cm,width=0.5\\columnwidth]': '50%',
        '[width=200pt]': '200pt',
        '[trim={0 0 0 0},clip]': None,            # no width= key
    }
    for opt, expected in cases.items():
        body = f'\\includegraphics{opt}{{p.pdf}}\n\\caption{{C.}}\n\\label{{fig:x}}\n'
        spec = parse_figure_block(body, placement=None)
        assert spec is not None, opt
        assert spec.width == expected, f'{opt} → {spec.width!r}, want {expected!r}'


def test_parse_strips_label_embedded_in_caption():
    """#98 #2: the ``\\caption{\\label{fig:x} Text}`` idiom must not leave
    the ``\\label`` inside ``spec.caption`` — otherwise pandoc emits a
    ``[]{#…}`` span and a stray leading space survives into the rendered
    caption. The label is captured separately as ``spec.name``."""
    body = (
        '\\includegraphics{p.pdf}\n'
        '\\caption{\\label{f:distributional_dp} Iterating $D_\\sigma$ here}\n'
    )
    spec = parse_figure_block(body, placement=None)
    assert spec is not None
    assert spec.name == 'f-distributional_dp'
    assert spec.caption == 'Iterating $D_\\sigma$ here'   # no \label, no lead space


def test_parse_includegraphics_path_on_next_line():
    """#98 #4: ``\\includegraphics[opts]`` whose ``{path}`` sits on the next
    line (dp1 ``f-finite_lq_1``, wrapped in ``\\scalebox`` with a ``[trim=…]``
    option) must still be found — the old regex required ``[…]{path}``
    adjacency and dropped the image entirely."""
    body = (
        '\\scalebox{0.64}{\\includegraphics[trim={0em 0em 0em 0em},clip]\n'
        '    {../figures/finite_lq_1.pdf}} % l, b, r, t\n'
        '\\caption{\\label{f:finite_lq_1} Simulation}\n'
    )
    spec = parse_figure_block(body, placement=None)
    assert spec is not None
    assert spec.image_src == '../figures/finite_lq_1.pdf'
    assert spec.name == 'f-finite_lq_1'
    assert spec.width is None                              # trim/clip, no width


def test_emit_width_renders_width_option_after_name():
    """The resolver emits ``:width:`` immediately after ``:name:`` (option
    order matches the legacy ``convert_figures`` emitter)."""
    spec = FigureSpec(name='fig-w', image_src='p.pdf', width='95%',
                      caption='Cap.')
    out = resolve_figure_markers(_wrap(encode_marker(spec)))
    assert ':name: fig-w' in out
    assert ':width: 95%' in out
    assert out.index(':name:') < out.index(':width:')


# ── 2. Marker encode/decode round-trip ──────────────────────────────────────


def test_encode_decode_preserves_all_fields():
    """JSON+base64 round-trip preserves every FigureSpec field."""
    spec = FigureSpec(
        name='fig-x', caption='Caption with [[CITEP:K]].',
        image_src='figures/x.pdf', tikz_input=None,
        sub_captions=['(a) one', '(b) two'], placement='ht',
    )
    marker = encode_marker(spec)
    assert marker.startswith('<!--FIGURE payload=')
    assert marker.endswith('-->')
    payload = marker[len('<!--FIGURE payload='):-len('-->')]
    spec2 = decode_marker(payload)
    assert spec2 == spec


def test_encode_marker_is_single_line():
    """Marker is a single line — pandoc must treat it as a self-
    contained block. Mirrors the table marker."""
    spec = FigureSpec(name='fig-x', caption='X', image_src='x.pdf',
                      sub_captions=['a', 'b'])
    marker = encode_marker(spec)
    assert '\n' not in marker


# ── 3. Post-pandoc resolver ─────────────────────────────────────────────────


def _wrap(marker: str) -> str:
    """Wrap a marker in surrounding prose to mirror the post-pandoc
    text the resolver actually sees."""
    return f'Before.\n\n{marker}\n\nAfter.\n'


def test_resolve_marker_with_image_emits_figure_directive():
    spec = FigureSpec(name='fig-x', caption='A caption.',
                      image_src='plot.pdf')
    out = resolve_figure_markers(_wrap(encode_marker(spec)))
    assert '```{figure} figures/plot.pdf' in out
    assert ':name: fig-x' in out
    assert 'A caption.' in out


def test_resolve_marker_preserves_explicit_path():
    """When the image src already contains a slash, the resolver
    doesn't re-prefix ``figures/``."""
    spec = FigureSpec(name='fig-x', image_src='path/to/plot.svg',
                      caption='C.')
    out = resolve_figure_markers(_wrap(encode_marker(spec)))
    assert '```{figure} path/to/plot.svg' in out


def test_resolve_marker_with_tikz_input_emits_admonition():
    """TIKZ input becomes the same admonition placeholder shape that
    ``convert_html_figures`` emits — so ``resolve_tikz_figures``
    substitutes via ``TIKZ_FIGURE_MAP`` in the same downstream step."""
    spec = FigureSpec(name='fig-t', tikz_input='diagram',
                      caption='TikZ caption.')
    out = resolve_figure_markers(_wrap(encode_marker(spec)))
    assert '```{admonition} Figure (TikZ — needs manual conversion)' in out
    assert ':name: fig-t' in out
    assert 'TikZ caption.' in out


def test_resolve_marker_sub_captions_before_main_caption():
    """Sub-captions fold ahead of the main caption in source order —
    same convention as PR #91's convert_html_figures fix, so the
    visible output is consistent across both code paths."""
    spec = FigureSpec(
        name='fig-x', image_src='x.pdf', caption='Main caption.',
        sub_captions=['(a) first panel', '(b) second panel'],
    )
    out = resolve_figure_markers(_wrap(encode_marker(spec)))
    # Order: (a) before (b) before main.
    pa = out.index('(a) first panel')
    pb = out.index('(b) second panel')
    pm = out.index('Main caption.')
    assert pa < pb < pm


def test_resolve_handles_pandoc_escaped_marker_brackets():
    """Pandoc may escape ``<`` / ``>`` to ``\\<`` / ``\\>`` on
    LaTeX→Markdown — the resolver must tolerate both forms, same as
    every other marker decoder in the codebase."""
    spec = FigureSpec(name='fig-e', image_src='x.pdf', caption='C.')
    marker = encode_marker(spec)
    escaped = marker.replace('<', '\\<').replace('>', '\\>')
    out = resolve_figure_markers(escaped)
    assert '```{figure} figures/x.pdf' in out


def test_resolve_leaves_malformed_marker_in_place():
    """Defensive: a garbled payload doesn't drop the figure silently —
    the marker stays so a human can see something went wrong."""
    bad = '<!--FIGURE payload=not-valid-base64!-->'
    assert resolve_figure_markers(bad) == bad


@pytest.mark.parametrize('payload', [
    'not_valid_base64!',                     # binascii.Error path
    'aGVsbG8=',                              # valid base64, NOT valid JSON
    base_payload := 'AAAA',                  # 3 NUL bytes, not utf-8 → JSON
])
def test_resolve_marker_corrupt_payload_does_not_crash(payload):
    """Copilot review on PR #95: ``base64.b64decode`` raises
    ``binascii.Error`` and ``.decode('utf-8')`` raises
    ``UnicodeDecodeError``. Both must be caught so a corrupt marker
    doesn't crash the whole postprocess pipeline (mirrors
    ``resolve_table_markers``'s broad ``except Exception``)."""
    bad = f'<!--FIGURE payload={payload}-->'
    # Must not raise — output keeps the marker in place verbatim.
    out = resolve_figure_markers(bad)
    assert out == bad


# ── 5. Defensive: comment skip + multi-image bail (Copilot #95) ─────────────


def test_preprocessor_skips_commented_figure_block():
    """Issue caught by Copilot review on PR #95: a ``\\begin{figure}``
    on a line disabled with ``%`` must NOT be marker-ized — otherwise
    the marker un-comments the figure and silently changes document
    semantics. Mirrors the ``_starts_in_comment`` guard in
    ``_apply_table_markers``."""
    src = (
        'Real text.\n\n'
        '% \\begin{figure}\n'
        '% \\includegraphics{x.pdf}\n'
        '% \\caption{Commented out, must stay so.}\n'
        '% \\label{fig:commented}\n'
        '% \\end{figure}\n\n'
        'More text.\n'
    )
    out = pre.process_text(src)
    # No marker emitted — block left exactly as it was.
    assert '<!--FIGURE' not in out
    assert '% \\begin{figure}' in out


def test_parse_bails_on_multi_image_figure():
    """Issue caught by Copilot review on PR #95: a figure containing
    multiple ``\\includegraphics`` (side-by-side panels without
    ``\\begin{subfigure}``) would silently drop all but the first
    image if we proceeded. Bail and fall through to the HTML path
    instead — Phase 1 is single-figure scope only."""
    body = (
        '\\includegraphics{a.pdf}\\hfill\n'
        '\\includegraphics{b.pdf}\n'
        '\\caption{Side-by-side panels.}\n'
        '\\label{fig:sidebyside}\n'
    )
    assert parse_figure_block(body, placement=None) is None


def test_parse_bails_on_mixed_includegraphics_and_tikz():
    """Same bail for one ``\\includegraphics`` + one ``\\input{tikz/...}``
    in the same figure — also multi-image, same Phase 1 scope rule."""
    body = (
        '\\includegraphics{a.pdf}\n'
        '\\input{tikz/b.tex}\n'
        '\\caption{Mixed sources.}\n'
        '\\label{fig:mixed}\n'
    )
    assert parse_figure_block(body, placement=None) is None


def test_parse_single_includegraphics_still_handled():
    """Regression guard for the bail above: a SINGLE
    ``\\includegraphics`` still produces a spec — the bail is only on
    multi-image."""
    body = (
        '\\includegraphics{single.pdf}\n'
        '\\caption{One image.}\n'
        '\\label{fig:one}\n'
    )
    spec = parse_figure_block(body, placement=None)
    assert spec is not None
    assert spec.image_src == 'single.pdf'


# ── 6. TIKZ_FIGURE_MAP integration (issue #96) ──────────────────────────────


def test_emit_consults_tikz_figure_map_for_inline_tikzpicture():
    """Closes #96: a ``\\begin{figure}\\begin{tikzpicture}…\\caption\\label``
    block has no ``\\includegraphics`` and no ``\\input{tikz/...}`` — but
    if its label has a ``TIKZ_FIGURE_MAP`` entry (populated from the
    consumer book's ``tikz_overrides.py``), the resolver must emit a
    ``{figure}`` directive with the mapped path. The previous Phase 1
    emitted a generic admonition and dropped 78/88 figures in DL R14."""
    import postprocess
    saved = dict(postprocess.TIKZ_FIGURE_MAP)
    try:
        postprocess.TIKZ_FIGURE_MAP['fig-foo'] = (
            'figures/fig-foo.svg', None,
        )
        spec = FigureSpec(
            name='fig-foo',
            caption='Body caption.',
            image_src=None,        # no \includegraphics — inline tikz
            tikz_input=None,        # no \input{tikz/...} either
        )
        out = resolve_figure_markers(_wrap(encode_marker(spec)))
        assert '```{figure} figures/fig-foo.svg' in out
        assert ':name: fig-foo' in out
        assert 'Body caption.' in out
        # NOT an admonition — the regression that #96 reported.
        assert '{admonition}' not in out
    finally:
        postprocess.TIKZ_FIGURE_MAP.clear()
        postprocess.TIKZ_FIGURE_MAP.update(saved)


def test_emit_tikz_map_caption_override_replaces_source_caption():
    """When ``TIKZ_FIGURE_MAP[label] == (path, caption_override)`` and
    ``caption_override`` is non-None, it replaces the extracted caption
    body. Matches the legacy ``resolve_tikz_figures`` semantics —
    consumer books override captions for figures whose source caption
    is wrong / outdated relative to the pre-rendered SVG."""
    import postprocess
    saved = dict(postprocess.TIKZ_FIGURE_MAP)
    try:
        postprocess.TIKZ_FIGURE_MAP['fig-x'] = (
            'figures/fig-x.svg', 'Authoritative caption from map.',
        )
        spec = FigureSpec(
            name='fig-x',
            caption='Original source caption (should be replaced).',
        )
        out = resolve_figure_markers(_wrap(encode_marker(spec)))
        assert 'Authoritative caption from map.' in out
        assert 'Original source caption' not in out
    finally:
        postprocess.TIKZ_FIGURE_MAP.clear()
        postprocess.TIKZ_FIGURE_MAP.update(saved)


def test_emit_tikz_map_lookup_for_input_tikz_form():
    """``\\input{tikz/stem}`` form: ``spec.tikz_input`` is set AND the
    label has a map entry — emit ``{figure}`` with the mapped path
    (not the admonition placeholder)."""
    import postprocess
    saved = dict(postprocess.TIKZ_FIGURE_MAP)
    try:
        postprocess.TIKZ_FIGURE_MAP['fig-tikz'] = (
            'figures/fig-tikz.svg', None,
        )
        spec = FigureSpec(
            name='fig-tikz',
            caption='Caption.',
            tikz_input='tikz-source-stem',
        )
        out = resolve_figure_markers(_wrap(encode_marker(spec)))
        assert '```{figure} figures/fig-tikz.svg' in out
        assert '{admonition}' not in out
    finally:
        postprocess.TIKZ_FIGURE_MAP.clear()
        postprocess.TIKZ_FIGURE_MAP.update(saved)


def test_emit_subfigure_per_subfigure_optout_expands_panels():
    """#75: a subfigure float whose outer label has a map entry tagged
    ``'per-subfigure'`` must NOT collapse to the single mapped image —
    the entry is not a composite. Panel expansion proceeds normally."""
    import postprocess
    saved = dict(postprocess.TIKZ_FIGURE_MAP)
    try:
        postprocess.TIKZ_FIGURE_MAP['fig-panels'] = (
            'figures/panel_a.svg', None, 'per-subfigure',
        )
        spec = FigureSpec(
            name='fig-panels',
            caption='Outer caption.',
            subfigures=[
                {'name': None, 'image_src': 'a.pdf', 'caption': 'Panel A.'},
                {'name': None, 'image_src': 'b.pdf', 'caption': 'Panel B.'},
            ],
        )
        out = resolve_figure_markers(_wrap(encode_marker(spec)))
        # Two panel figures, not one collapsed composite.
        assert out.count('```{figure}') == 2
        assert 'Panel A.' in out
        assert 'Panel B.' in out
        assert 'figures/panel_a.svg' not in out
    finally:
        postprocess.TIKZ_FIGURE_MAP.clear()
        postprocess.TIKZ_FIGURE_MAP.update(saved)


def test_emit_subfigure_composite_override_still_wins_by_default():
    """Regression guard for the #94/#98 semantics: an outer-label map
    entry WITHOUT the ``'per-subfigure'`` tag still collapses the float
    to the single composite image."""
    import postprocess
    saved = dict(postprocess.TIKZ_FIGURE_MAP)
    try:
        postprocess.TIKZ_FIGURE_MAP['fig-comp'] = (
            'figures/composite.svg', None,
        )
        spec = FigureSpec(
            name='fig-comp',
            caption='Outer caption.',
            subfigures=[
                {'name': None, 'image_src': 'a.pdf', 'caption': 'Panel A.'},
                {'name': None, 'image_src': 'b.pdf', 'caption': 'Panel B.'},
            ],
        )
        out = resolve_figure_markers(_wrap(encode_marker(spec)))
        assert out.count('```{figure}') == 1
        assert '```{figure} figures/composite.svg' in out
    finally:
        postprocess.TIKZ_FIGURE_MAP.clear()
        postprocess.TIKZ_FIGURE_MAP.update(saved)


def test_emit_falls_back_to_admonition_when_no_map_entry():
    """A figure with no image source and a label NOT in the map should
    still emit a labelled admonition so the caption survives. Mirrors
    the pre-#96 fallback so consumers without a tikz_overrides.py keep
    getting captions even when figures aren't pre-rendered."""
    import postprocess
    saved = dict(postprocess.TIKZ_FIGURE_MAP)
    try:
        postprocess.TIKZ_FIGURE_MAP.clear()
        spec = FigureSpec(name='fig-unmapped', caption='No image, just text.')
        out = resolve_figure_markers(_wrap(encode_marker(spec)))
        assert '```{admonition} Figure' in out
        assert ':name: fig-unmapped' in out
        assert 'No image, just text.' in out
    finally:
        postprocess.TIKZ_FIGURE_MAP.clear()
        postprocess.TIKZ_FIGURE_MAP.update(saved)


def test_emit_includegraphics_path_wins_over_tikz_map():
    """Priority: an explicit ``\\includegraphics{path}`` in source takes
    precedence over a ``TIKZ_FIGURE_MAP`` entry under the same label.
    Defensive ordering — the source path is the author's literal
    intent; map entries are project-level overrides for figures
    that *don't* have a source path."""
    import postprocess
    saved = dict(postprocess.TIKZ_FIGURE_MAP)
    try:
        postprocess.TIKZ_FIGURE_MAP['fig-collide'] = (
            'figures/from-map.svg', None,
        )
        spec = FigureSpec(
            name='fig-collide',
            caption='C.',
            image_src='from-source.pdf',
        )
        out = resolve_figure_markers(_wrap(encode_marker(spec)))
        assert 'from-source.pdf' in out
        assert 'from-map.svg' not in out
    finally:
        postprocess.TIKZ_FIGURE_MAP.clear()
        postprocess.TIKZ_FIGURE_MAP.update(saved)


def test_emit_tikz_map_path_emitted_verbatim_no_figures_prefix():
    """Caught by Copilot review on PR #97: legacy ``resolve_tikz_figures``
    emits the ``TIKZ_FIGURE_MAP`` value verbatim (no ``figures/`` prefix
    added). My first pass collapsed this through the same path-
    completion helper as ``\\includegraphics``, so a map entry like
    ``'fig-x': ('plain.svg', None)`` would have been silently rerouted
    to ``figures/plain.svg`` — wrong for any consumer book using bare
    filenames or non-``figures/`` roots. The mapped path must round-
    trip exactly as configured."""
    import postprocess
    saved = dict(postprocess.TIKZ_FIGURE_MAP)
    try:
        # Three shapes that would each be mangled by ``figures/``-
        # prefixing: bare filename, root-relative non-figures path, and
        # absolute path.
        for path in ['plain.svg', 'assets/foo.svg', '/abs/path.svg']:
            postprocess.TIKZ_FIGURE_MAP.clear()
            postprocess.TIKZ_FIGURE_MAP['fig-x'] = (path, None)
            spec = FigureSpec(name='fig-x', caption='C.')
            out = resolve_figure_markers(_wrap(encode_marker(spec)))
            assert f'```{{figure}} {path}' in out, (
                f'path {path!r} got rewritten in output:\n{out}'
            )
            assert 'figures/' + path not in out
    finally:
        postprocess.TIKZ_FIGURE_MAP.clear()
        postprocess.TIKZ_FIGURE_MAP.update(saved)


def test_emit_includegraphics_bare_filename_still_gets_figures_prefix():
    """Regression guard for the asymmetry: bare ``\\includegraphics{x.pdf}``
    (no slash in path) still gets the ``figures/`` prefix, mirroring
    ``figures.make_figure``. Only map entries are emitted verbatim;
    source-side paths still get path-completion."""
    spec = FigureSpec(name='fig-bare', image_src='plot.pdf', caption='X.')
    out = resolve_figure_markers(_wrap(encode_marker(spec)))
    assert '```{figure} figures/plot.pdf' in out


# ── 4. End-to-end (preprocessor → pandoc → resolver → natbib decode) ────────


@pytest.mark.skipif(not PANDOC_AVAILABLE, reason='pandoc not on PATH')
def test_e2e_citep_in_figure_caption_closes_issue_92():
    """Issue #92: ``\\citep{X}`` in a figure caption was leaking as a
    literal ``[[CITEP:X]]`` token. After the marker pipeline it should
    resolve to ``{cite:p}`X```."""
    # Simulate the post-_apply_rewrites form (citep already rewritten).
    src = (
        '\\begin{figure}[ht]\n'
        '\\includegraphics{lr.pdf}\n'
        '\\caption{cosine annealing [[CITEP:loshchilov2017sgdr]] is great.}\n'
        '\\label{fig:lr}\n'
        '\\end{figure}\n'
    )
    out = pre.process_text(src)
    # Pandoc happens here in the real pipeline; for the test we go
    # straight from the markered text into the post-pandoc steps.
    out = resolve_figure_markers(out)
    out = decode_natbib_markers(out)
    out = convert_citations(out)
    assert '{cite:p}`loshchilov2017sgdr`' in out


@pytest.mark.skipif(not PANDOC_AVAILABLE, reason='pandoc not on PATH')
def test_e2e_citet_in_figure_caption_closes_issue_89():
    """Issue #89 (now via marker path): ``\\citet{X}`` in a figure
    caption should resolve to ``{cite:t}`X```. The marker pipeline
    handles this through the natbib-rewrite-then-pandoc path."""
    # NB: \citet is NOT pre-rewritten by _apply_rewrites (it goes via
    # pandoc native @key form) — so it arrives at the marker preprocessor
    # as raw \citet{X}, gets pandoc-converted in the batch.
    src = (
        '\\begin{figure}\n'
        '\\includegraphics{x.pdf}\n'
        '\\caption{DGM architecture of \\citet{sirignano2018dgm}.}\n'
        '\\label{fig:dgm}\n'
        '\\end{figure}\n'
    )
    out = pre.process_text(src)
    out = resolve_figure_markers(out)
    out = decode_natbib_markers(out)
    out = convert_citations(out)
    assert '{cite:t}`sirignano2018dgm`' in out


@pytest.mark.skipif(not PANDOC_AVAILABLE, reason='pandoc not on PATH')
def test_e2e_raw_tikzpicture_caption_only_node_labels_dropped_closes_issue_98_3():
    """#98 #3 + Phase 6: a figure wrapping a raw ``\\begin{tikzpicture}`` with
    ``{\\footnotesize}`` node labels is now marker-ized **caption-only** — the
    tikz body is stripped, so node labels (``$a_3$``) are NOT scooped, while
    the float caption + label are carried (math intact). ``_emit_figure``
    resolves the image from ``TIKZ_FIGURE_MAP``; node text must NOT appear in
    the caption. Mirrors dp2 ``f-coase_no``."""
    import postprocess
    src = (
        '\\begin{figure}\n'
        '\\begin{tikzpicture}\n'
        '\\node {\\footnotesize $a_3$};\n'
        '\\node {\\footnotesize $a_2$};\n'
        '\\end{tikzpicture}\n'
        '\\caption{\\label{f:coase_no} Notation}\n'
        '\\end{figure}\n'
    )
    markered = pre.process_text(src)
    assert '<!--FIGURE' in markered               # caption-only marker emitted
    r = subprocess.run(
        ['pandoc', '-f', 'latex', '-t', 'markdown', '--wrap=none'],
        input=markered, capture_output=True, text=True, check=True,
    )
    saved = dict(postprocess.TIKZ_FIGURE_MAP)
    try:
        postprocess.TIKZ_FIGURE_MAP.clear()
        postprocess.TIKZ_FIGURE_MAP['f-coase_no'] = ('figures/coase_no.svg', None)
        out = resolve_figure_markers(r.stdout)    # override → mapped SVG + caption
    finally:
        postprocess.TIKZ_FIGURE_MAP.clear()
        postprocess.TIKZ_FIGURE_MAP.update(saved)
    assert '```{figure} figures/coase_no.svg' in out
    assert ':name: f-coase_no' in out
    assert 'Notation' in out
    assert 'a_3' not in out and 'a_2' not in out  # node text NOT leaked (#98 #3)
    assert ':name: f-coase_no' in out
    assert 'Notation' in out
    # Tikz node labels must NOT leak into the caption.
    assert '$a_3$' not in out
    assert '$a_2$' not in out


@pytest.mark.skipif(not PANDOC_AVAILABLE, reason='pandoc not on PATH')
def test_e2e_paren_leading_caption_not_math_escaped():
    """A caption that STARTS with ``(a)`` would normally trigger pandoc's
    ``(a)`` → ``\\(a\\)`` (inline math) misinterpretation. The preprocessor
    prefixes each batch cell with ``~`` (LaTeX nbsp) to avoid this —
    strip-equivalent in the markdown output. Exercised on a plain
    ``\\includegraphics`` figure (the tikz shape now bails, #98 #3)."""
    src = (
        '\\begin{figure}\n'
        '\\includegraphics{panel.pdf}\n'
        '\\caption{(a) the unit ball inscribed in cube}\n'
        '\\label{fig:vp}\n'
        '\\end{figure}\n'
    )
    out = pre.process_text(src)
    out = resolve_figure_markers(out)
    # The (a) survives as text — not converted to inline math \(a\).
    assert '(a) the unit ball inscribed in cube' in out
    assert '\\(a\\)' not in out


@pytest.mark.skipif(not PANDOC_AVAILABLE, reason='pandoc not on PATH')
def test_e2e_subfigure_includegraphics_marker_ized():
    """#94 (Phase 4): a figure whose subfigure panels are plain
    ``\\includegraphics`` is now marker-ized by the preprocessor (one marker
    for the float, expanded to N ``{figure}`` directives post-pandoc)."""
    src = (
        '\\begin{figure}\n'
        '\\begin{subfigure}{0.5\\textwidth}\n'
        '\\includegraphics{a.pdf}\n'
        '\\caption{Sub a.}\n'
        '\\end{subfigure}\n'
        '\\caption{Outer.}\n'
        '\\label{fig:outer}\n'
        '\\end{figure}\n'
    )
    out = pre.process_text(src)
    # A FIGURE marker IS emitted; the raw subfigure env is gone.
    assert '<!--FIGURE' in out
    assert '\\begin{subfigure}' not in out


@pytest.mark.skipif(not PANDOC_AVAILABLE, reason='pandoc not on PATH')
def test_e2e_scalebox_subfigure_block_still_bails():
    """A subfigure float with a non-``\\includegraphics`` panel
    (``\\scalebox{\\input{…}}``) still bails — left for the HTML path."""
    src = (
        '\\begin{figure}\n'
        '\\begin{subfigure}{0.5\\textwidth}\n'
        '\\scalebox{0.45}{\\input{../figures/x.pdf_t}}\n'
        '\\caption{}\n'
        '\\end{subfigure}\n'
        '\\caption{Outer.}\n'
        '\\label{fig:outer}\n'
        '\\end{figure}\n'
    )
    out = pre.process_text(src)
    assert '<!--FIGURE' not in out
    assert '\\begin{subfigure}' in out
