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


def test_parse_bails_on_subfigure():
    """Phase 1 bails on any ``\\begin{subfigure}`` — those blocks fall
    through to ``convert_html_figures`` for the existing handling
    (issue #94 tracks Phase 2)."""
    body = (
        '\\begin{subfigure}{0.5\\textwidth}\n'
        '\\includegraphics{a.pdf}\n'
        '\\end{subfigure}\n'
        '\\caption{Outer.}\n'
    )
    assert parse_figure_block(body, placement=None) is None


def test_parse_bare_footnotesize_subcaption_extracted():
    """Issue #93: ``{\\footnotesize ...}`` directly inside the figure
    body (no ``\\begin{minipage}`` wrapper) was previously dropped.
    The parser now captures it as a sub-caption."""
    body = (
        '\\begin{tikzpicture}\\end{tikzpicture}\n'
        '{\\footnotesize Verification: $0.05 = m$.}\n'
        '\\caption{Main caption.}\n'
        '\\label{fig:young}\n'
    )
    spec = parse_figure_block(body, placement=None)
    assert spec is not None
    assert spec.sub_captions == ['Verification: $0.05 = m$.']


def test_parse_minipage_wrapped_footnotesize_subcaption_extracted():
    """Issue #90: ``{\\footnotesize ...}`` inside a ``\\begin{minipage}``
    is also captured (the wrapper doesn't affect extraction)."""
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
    assert spec.sub_captions == ['(a) the unit ball']


def test_parse_multiple_subcaptions_in_source_order():
    """Two minipages → two sub-captions, in source order."""
    body = (
        '\\begin{minipage}{0.4\\textwidth}\n'
        '\\begin{tikzpicture}\\end{tikzpicture}\\\\\n'
        '{\\footnotesize (a) first}\n'
        '\\end{minipage}\\hfill\n'
        '\\begin{minipage}{0.5\\textwidth}\n'
        '\\begin{tikzpicture}\\end{tikzpicture}\\\\\n'
        '{\\footnotesize (b) second}\n'
        '\\end{minipage}\n'
        '\\caption{Main.}\n'
        '\\label{fig:multi}\n'
    )
    spec = parse_figure_block(body, placement=None)
    assert spec is not None
    assert spec.sub_captions == ['(a) first', '(b) second']


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
def test_e2e_bare_footnotesize_subcaption_closes_issue_93():
    """Issue #93: bare ``{\\footnotesize ...}`` between ``\\end{tikzpicture}``
    and ``\\caption{}`` was dropped. Now it's captured as a sub-caption
    and folds into the figure body ahead of the main caption."""
    src = (
        '\\begin{figure}\n'
        '\\begin{tikzpicture}\\end{tikzpicture}\n'
        '{\\footnotesize Verification: $0.05 = m$.}\n'
        '\\caption{Main caption.}\n'
        '\\label{fig:young}\n'
        '\\end{figure}\n'
    )
    out = pre.process_text(src)
    out = resolve_figure_markers(out)
    assert 'Verification: $0.05 = m$' in out
    assert 'Main caption.' in out
    # Sub-cap appears before main caption.
    assert out.index('Verification') < out.index('Main caption.')


@pytest.mark.skipif(not PANDOC_AVAILABLE, reason='pandoc not on PATH')
def test_e2e_paren_sub_caption_not_math_escaped():
    """A sub-caption that STARTS with ``(a)`` would normally trigger
    pandoc's ``(a)`` → ``\\(a\\)`` (inline math) misinterpretation.
    The preprocessor prefixes each batch cell with ``~`` (LaTeX nbsp)
    to avoid this — strip-equivalent in the markdown output."""
    src = (
        '\\begin{figure}\n'
        '\\begin{minipage}{0.4\\textwidth}\n'
        '\\begin{tikzpicture}\\end{tikzpicture}\\\\\n'
        '{\\footnotesize (a) the unit ball inscribed in cube}\n'
        '\\end{minipage}\n'
        '\\caption{Main.}\n'
        '\\label{fig:vp}\n'
        '\\end{figure}\n'
    )
    out = pre.process_text(src)
    out = resolve_figure_markers(out)
    # The (a) survives as text — not converted to inline math \(a\).
    assert '(a) the unit ball inscribed in cube' in out
    assert '\\(a\\)' not in out


@pytest.mark.skipif(not PANDOC_AVAILABLE, reason='pandoc not on PATH')
def test_e2e_subfigure_block_bails_to_existing_path():
    """A figure block containing ``\\begin{subfigure}`` is left unchanged
    by the marker preprocessor (Phase 1 bail). Pandoc handles it; the
    existing ``convert_html_figures`` path takes over post-pandoc."""
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
    # No FIGURE marker emitted — block unchanged.
    assert '<!--FIGURE' not in out
    assert '\\begin{subfigure}' in out
