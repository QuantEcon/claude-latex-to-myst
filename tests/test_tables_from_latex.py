"""Unit tests for ``scripts/transforms/tables_from_latex.py``.

Covers the LaTeX-tabular parser that closes #51 — the marker
preprocessor's structural extraction step. Cells contain raw LaTeX
at parse time (the preprocessor converts them to markdown via pandoc
before writing markers); tests use bare-LaTeX cell content to keep
the parser's contract clear.
"""

from __future__ import annotations

from pathlib import Path

from transforms.tables_from_latex import (
    TableSpec,
    decode_marker,
    emit_myst,
    encode_marker,
    find_table_blocks,
    parse_table_block,
)


def test_finds_simple_table_block():
    src = (
        r'\begin{table}' '\n'
        r'\begin{tabular}{lc}' '\n'
        r'\hline' '\n'
        r'A & B \\' '\n'
        r'\hline' '\n'
        r'1 & 2 \\' '\n'
        r'\hline' '\n'
        r'\end{tabular}' '\n'
        r'\caption{Test}' '\n'
        r'\label{tab:t1}' '\n'
        r'\end{table}'
    )
    blocks = find_table_blocks(src)
    assert len(blocks) == 1
    start, end, body = blocks[0]
    assert src[start:end] == src  # the whole source IS the block


def test_finds_table_with_position_arg():
    src = (
        r'\begin{table}[ht]' '\n'
        r'\begin{tabular}{l}' '\n'
        r'A \\' '\n'
        r'\end{tabular}' '\n'
        r'\end{table}'
    )
    blocks = find_table_blocks(src)
    assert len(blocks) == 1


def test_skips_commented_block():
    src = (
        r'% \begin{table}' '\n'
        r'% \begin{tabular}{l}' '\n'
        r'% A \\' '\n'
        r'% \end{tabular}' '\n'
        r'% \end{table}' '\n'
    )
    blocks = find_table_blocks(src)
    assert blocks == []


def test_parses_two_header_rows_separated_by_single_hline():
    """The dp2 ``tab:convergence_cases`` shape: 2 header rows above
    a single ``\\hline``, then body rows below — pandoc would collapse
    the interior rule, but our parser sees it directly."""
    body = (
        r'\centering' '\n'
        r'\begin{tabular}{lccc}' '\n'
        r'\hline\hline' '\n'
        r'& Case I & Case II & Case III \\' '\n'
        r'& Ref1 & Ref2 & Ref3 \\' '\n'
        r'\hline' '\n'
        r'Regular & a & b & c \\' '\n'
        r'Order stable & d & e & f \\' '\n'
        r'\hline\hline' '\n'
        r'\end{tabular}' '\n'
        r'\caption{Caption text}' '\n'
        r'\label{tab:conv}' '\n'
    )
    spec = parse_table_block(body)
    assert spec is not None
    assert spec.name == 'tab-conv'
    assert spec.caption == 'Caption text'
    assert spec.colspec == ['l', 'c', 'c', 'c']
    assert len(spec.header_rows) == 2
    assert spec.header_rows[0] == ['', 'Case I', 'Case II', 'Case III']
    assert spec.header_rows[1] == ['', 'Ref1', 'Ref2', 'Ref3']
    assert len(spec.body_rows) == 2
    assert spec.body_rows[0] == ['Regular', 'a', 'b', 'c']


def test_parses_booktabs_toprule_midrule_bottomrule():
    body = (
        r'\begin{tabular}{lcc}' '\n'
        r'\toprule' '\n'
        r'Symbol & Meaning & Value \\' '\n'
        r'\midrule' '\n'
        r'$x$ & state & 1.0 \\' '\n'
        r'$y$ & action & 0.5 \\' '\n'
        r'\bottomrule' '\n'
        r'\end{tabular}' '\n'
        r'\caption{Notation}' '\n'
        r'\label{tab:notation}' '\n'
    )
    spec = parse_table_block(body)
    assert spec.name == 'tab-notation'
    assert spec.caption == 'Notation'
    assert spec.colspec == ['l', 'c', 'c']
    assert len(spec.header_rows) == 1
    assert spec.header_rows[0] == ['Symbol', 'Meaning', 'Value']
    assert len(spec.body_rows) == 2
    assert spec.body_rows[0] == [r'$x$', 'state', '1.0']


def test_colspec_skips_post_cell_modifier_with_letters_inside():
    """``<{...}`` is a post-cell content modifier (mirror of ``>{...}``).
    Its braced argument can contain LaTeX commands that include
    ``l``/``c``/``r`` characters (``\\bfseries``, ``\\centering``,
    ``\\raggedright``) — those must NOT be parsed as real columns.

    Surfaced by Copilot's review of PR #53: the original code skipped
    ``>{...}`` but not ``<{...}``, so a colspec like
    ``@{}>{$}l<{\\bfseries\\centering}@{}}`` would emit spurious ``c``
    and ``r`` column entries from the modifier body."""
    body = (
        r'\begin{tabular}{@{}>{$}l<{\bfseries\centering}'
        r'>{$}c<{\raggedright}@{}}' '\n'
        r'\hline' '\n'
        r'A & B \\' '\n'
        r'\hline' '\n'
        r'1 & 2 \\' '\n'
        r'\hline' '\n'
        r'\end{tabular}'
    )
    spec = parse_table_block(body)
    # Two real columns: ``l`` and ``c``. NOT 5+ from the letters
    # inside ``\bfseries\centering`` / ``\raggedright``.
    assert spec.colspec == ['l', 'c'], (
        f'expected 2 columns from spec; got {len(spec.colspec)}: '
        f'{spec.colspec!r}'
    )


def test_parses_nested_brace_colspec():
    """Real-world Deep-Learning shape: ``\\begin{tabular}{@{}>{...}p{...}...@{}}``
    — nested braces in the column spec must be balanced correctly,
    not clipped at the first ``}``."""
    body = (
        r'\begin{tabular}{@{}>{\raggedright\arraybackslash}p{0.19\linewidth}'
        r'>{\raggedright\arraybackslash}p{0.35\linewidth}'
        r'>{\raggedright\arraybackslash}p{0.36\linewidth}@{}}' '\n'
        r'\toprule' '\n'
        r'& \textbf{Brock-Mirman} & \textbf{IRBC} \\' '\n'
        r'\midrule' '\n'
        r'Countries & 1 & $N$ \\' '\n'
        r'\bottomrule' '\n'
        r'\end{tabular}' '\n'
        r'\caption{Compare}' '\n'
    )
    spec = parse_table_block(body)
    # Three p{...} columns → ['l', 'l', 'l'].
    assert spec.colspec == ['l', 'l', 'l']
    assert spec.header_rows[0] == ['', r'\textbf{Brock-Mirman}', r'\textbf{IRBC}']
    assert spec.body_rows[0] == ['Countries', '1', '$N$']


def test_parses_cells_with_balanced_braces():
    """``\\textbf{Foo (Ch.~\\ref{ch:bar})}`` — cell content with nested
    braces must NOT be split by the ``&`` separator detector."""
    body = (
        r'\begin{tabular}{ll}' '\n'
        r'\hline' '\n'
        r'A & \textbf{Foo (Ch.~\ref{ch:bar})} \\' '\n'
        r'\hline' '\n'
        r'B & \cref{tab:x} and \cref{tab:y} \\' '\n'
        r'\hline' '\n'
        r'\end{tabular}' '\n'
    )
    spec = parse_table_block(body)
    assert spec.header_rows[0] == ['A', r'\textbf{Foo (Ch.~\ref{ch:bar})}']
    assert spec.body_rows[0] == ['B', r'\cref{tab:x} and \cref{tab:y}']


def test_label_inside_caption_extracted():
    """``\\caption{\\label{tab:foo} Caption text}`` form — label
    inside caption argument."""
    body = (
        r'\begin{tabular}{l}' '\n'
        r'A \\' '\n'
        r'\end{tabular}' '\n'
        r'\caption{\label{tab:in_caption} The caption.}' '\n'
    )
    spec = parse_table_block(body)
    assert spec.name == 'tab-in_caption'
    assert spec.caption == 'The caption.'


def test_no_tabular_returns_none():
    body = r'\begin{table} No tabular here \end{table}'.replace(
        r'\begin{table}', ''
    ).replace(r'\end{table}', '')
    assert parse_table_block(body) is None


def test_emit_myst_captioned_one_header_row_emits_pipe_table():
    spec = TableSpec(
        name='tab-foo',
        caption='Caption text.',
        colspec=['l', 'c', 'r'],
        header_rows=[['H1', 'H2', 'H3']],
        body_rows=[['a', 'b', 'c'], ['d', 'e', 'f']],
    )
    out = emit_myst(spec)
    assert '````{table}' in out
    assert ':name: tab-foo' in out
    assert 'Caption text.' in out
    assert '| H1 | H2 | H3 |' in out
    assert '|---|:---:|---:|' in out  # alignment from colspec
    assert '| a | b | c |' in out
    assert '| d | e | f |' in out
    assert '```{list-table}' not in out
    assert out.endswith('````')


def test_emit_myst_captioned_two_header_rows_falls_back_to_list_table():
    """Pipe-tables only support 1 header row; >=2 falls back to
    {list-table} fallback inside the {table} wrapper (which
    re-introduces the phantom-enumerator behaviour but only for the
    edge case)."""
    spec = TableSpec(
        name='tab-foo',
        caption='Cap.',
        colspec=['l', 'c'],
        header_rows=[['H1a', 'H2a'], ['H1b', 'H2b']],
        body_rows=[['a', 'b']],
    )
    out = emit_myst(spec)
    assert '````{table}' in out
    assert ':name: tab-foo' in out
    assert '```{list-table}' in out
    assert ':header-rows: 2' in out
    assert '* - H1a' in out
    assert '  - H2a' in out
    assert '* - H1b' in out
    assert '* - a' in out


def test_emit_myst_captioned_zero_header_rows_falls_back_to_list_table():
    spec = TableSpec(
        name='tab-foo',
        caption='Cap.',
        colspec=['l', 'l'],
        header_rows=[],
        body_rows=[['a', 'b'], ['c', 'd']],
    )
    out = emit_myst(spec)
    assert '````{table}' in out
    # Falls back to {list-table} with :header-rows: 0.
    assert '```{list-table}' in out
    assert ':header-rows: 0' in out
    # No synthetic blank pipe-table header row.
    assert '|  |  |' not in out


def test_emit_myst_uncaptioned_with_header_emits_bare_pipe_table():
    spec = TableSpec(
        name=None,
        caption=None,
        colspec=['l', 'l'],
        header_rows=[['Sym', 'Meaning']],
        body_rows=[['$x$', 'state']],
    )
    out = emit_myst(spec)
    assert '````{table}' not in out
    assert '| Sym | Meaning |' in out
    assert '|---|---|' in out
    assert '| $x$ | state |' in out


def test_emit_myst_labeled_without_caption_uses_table_wrapper():
    """A ``\\begin{table}`` with ``\\label`` but no ``\\caption`` still
    needs the ``{table}`` wrapper so ``:name:`` attaches to the
    enumerable container. Without the wrapper, a bare pipe-table has
    no way to carry the label and ``{numref}`tab-X`` wouldn't resolve."""
    spec = TableSpec(
        name='tab-labeled',
        caption=None,
        colspec=['l', 'l'],
        header_rows=[['Sym', 'Meaning']],
        body_rows=[['$x$', 'state']],
    )
    out = emit_myst(spec)
    assert '````{table}' in out
    assert ':name: tab-labeled' in out
    # No caption line, but body still present.
    assert '| Sym | Meaning |' in out
    assert out.endswith('````')


def test_emit_myst_escapes_pipe_in_cells():
    spec = TableSpec(
        name=None,
        caption=None,
        colspec=['l', 'l'],
        header_rows=[['Op', 'Result']],
        body_rows=[['AND', 'a | b']],
    )
    out = emit_myst(spec)
    assert r'a \| b' in out


def test_marker_round_trip():
    """``encode_marker`` → ``decode_marker`` preserves the TableSpec
    exactly. Marker is a single-line HTML comment so pandoc treats it
    as a self-contained block."""
    spec = TableSpec(
        name='tab-rt',
        caption='Round-trip test with $math$ and {ref}`x`.',
        colspec=['l', 'c'],
        header_rows=[['H1', 'H2']],
        body_rows=[['a', 'b'], ['c', 'd']],
    )
    marker = encode_marker(spec)
    assert '\n' not in marker  # single-line
    assert marker.startswith('<!--TABLE ')
    assert marker.endswith('-->')

    decoded = decode_marker(marker.split('payload=', 1)[1][:-len('-->')])
    assert decoded.name == spec.name
    assert decoded.caption == spec.caption
    assert decoded.colspec == spec.colspec
    assert decoded.header_rows == spec.header_rows
    assert decoded.body_rows == spec.body_rows


def test_emits_top_and_bottom_rule_sections_drop_when_empty():
    """``\\toprule``/``\\bottomrule`` produce empty sections at the
    top and bottom of the rule-split. These should be filtered out
    so the first non-empty section becomes the header."""
    body = (
        r'\begin{tabular}{ll}' '\n'
        r'\toprule' '\n'
        r'H1 & H2 \\' '\n'
        r'\midrule' '\n'
        r'a & b \\' '\n'
        r'\bottomrule' '\n'
        r'\end{tabular}'
    )
    spec = parse_table_block(body)
    assert spec.header_rows == [['H1', 'H2']]
    assert spec.body_rows == [['a', 'b']]


def test_interior_hline_in_body_keeps_rows_together():
    """A visual ``\\hline`` between body groups should NOT cause a
    second header section — the FIRST interior rule is the
    header/body boundary; subsequent rules are body separators."""
    body = (
        r'\begin{tabular}{ll}' '\n'
        r'\hline' '\n'
        r'H1 & H2 \\' '\n'
        r'\hline' '\n'
        r'a & b \\' '\n'
        r'\hline' '\n'
        r'c & d \\' '\n'
        r'\hline' '\n'
        r'\end{tabular}'
    )
    spec = parse_table_block(body)
    # First interior \hline separates header from body.
    assert spec.header_rows == [['H1', 'H2']]
    # ALL subsequent rows (across the visual separator) are body.
    assert spec.body_rows == [['a', 'b'], ['c', 'd']]


# ---------------------------------------------------------------------------
# Integration tests — marker preprocessor (process_text) + resolver round trip
# ---------------------------------------------------------------------------
# These import _apply_table_markers (which spawns pandoc) so they're skipped
# automatically if pandoc isn't on PATH.

import shutil  # noqa: E402

import pytest  # noqa: E402

PANDOC_AVAILABLE = shutil.which('pandoc') is not None


def _load_marker_preprocessor():
    """Load the ``_apply_table_markers`` module by path (it's a script,
    not on a package path). Returns the imported module."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        '_apply_table_markers',
        Path(__file__).resolve().parents[1] / 'scripts' / '_apply_table_markers.py',
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _process_text(src: str) -> str:
    """Helper: invoke the preprocessor's ``process_text`` on a string."""
    return _load_marker_preprocessor().process_text(src)


def test_pandoc_batch_convert_falls_back_to_original_cells_on_subprocess_failure(
    monkeypatch, capsys
):
    """Defensive: pandoc failures (binary missing, OOM, bad construct)
    must NOT take down the whole preprocess pass. ``_pandoc_batch_convert``
    falls back to returning the original cells unchanged; the rest of
    the marker pipeline then emits structurally-valid markers whose
    cells contain raw LaTeX. ``resolve_table_markers`` still emits
    ``{table}`` directives — content is worse than the happy path,
    but the build doesn't break."""
    import subprocess

    mod = _load_marker_preprocessor()

    def fake_run(*args, **kwargs):
        raise subprocess.CalledProcessError(
            returncode=1, cmd=args[0] if args else 'pandoc',
            stderr='simulated pandoc failure',
        )

    monkeypatch.setattr(subprocess, 'run', fake_run)

    cells = [r'\textbf{x}', r'$y$', 'plain']
    out = mod._pandoc_batch_convert(cells)
    # Fallback: returns the original (raw-LaTeX) cells.
    assert out == cells
    # Failure is logged to stderr so the author has a signal.
    captured = capsys.readouterr()
    assert 'pandoc batch conversion failed' in captured.err
    assert 'simulated pandoc failure' in captured.err


def test_pandoc_batch_convert_falls_back_when_pandoc_missing(monkeypatch, capsys):
    """A FileNotFoundError (pandoc not on PATH) is treated the same as
    a CalledProcessError — fall back to original cells, log to stderr.
    Without this guard, environments without pandoc would crash the
    preprocess pass entirely instead of degrading gracefully."""
    import subprocess

    mod = _load_marker_preprocessor()

    def fake_run(*args, **kwargs):
        raise FileNotFoundError('pandoc')

    monkeypatch.setattr(subprocess, 'run', fake_run)

    cells = ['cell']
    out = mod._pandoc_batch_convert(cells)
    assert out == cells
    assert 'FileNotFoundError' in capsys.readouterr().err


@pytest.mark.skipif(not PANDOC_AVAILABLE, reason='pandoc not on PATH')
def test_process_text_wraps_marker_in_blank_lines_when_prose_precedes_table():
    """Regression for PR #53 retest against Deep-Learning book: 5
    captioned tables lost their ``{table}`` directive because
    ``\\begin{table}`` sat IMMEDIATELY after a prose paragraph (no
    blank line in the .tex source). The marker substitution then
    glued the marker to the preceding paragraph; pandoc emitted it
    inline; ``resolve_table_markers`` expanded the multi-line
    ``\\`\\`\\`\\`{table}`` directive onto the same line as the prose,
    where MyST refuses to parse a directive. The fix wraps the
    marker in ``\\n\\n`` on both sides at substitution time.

    Affected sources in Deep-Learning included
    ``tab:olg6_savings_rates``, ``tab:pinn_failure_modes``,
    ``tab:cdice_tests`` and 2 others — all sharing the
    "prose-then-block-with-no-blank-line" shape.
    """
    src = (
        r'For $A=6$, $\beta=0.7$, Table~\ref{tab:foo} reports the rates.'
        '\n'  # NO blank line before \begin{table}
        r'\begin{table}[ht]' '\n'
        r'\begin{tabular}{ll}' '\n'
        r'\toprule' '\n'
        r'H1 & H2 \\' '\n'
        r'\midrule' '\n'
        r'a & b \\' '\n'
        r'\bottomrule' '\n'
        r'\end{tabular}' '\n'
        r'\caption{Cap}' '\n'
        r'\label{tab:foo}' '\n'
        r'\end{table}' '\n'
        r'After the table, more prose follows.'  # NO blank line after
    )
    out = _process_text(src)
    # The marker must be on its own line — preceded and followed by
    # blank lines so pandoc treats it as a standalone block.
    import re
    marker_match = re.search(
        r'\n\n<!--TABLE payload=[A-Za-z0-9+/=]+-->\n\n',
        out,
    )
    assert marker_match is not None, (
        f'marker must be wrapped in blank lines (paragraph break on '
        f'both sides); got:\n{out!r}'
    )
    # And the preceding prose / trailing prose must still be present
    # — we're isolating the marker, not eating context.
    assert 'For $A=6$' in out
    assert 'After the table, more prose follows.' in out


@pytest.mark.skipif(not PANDOC_AVAILABLE, reason='pandoc not on PATH')
def test_process_text_emits_marker_for_simple_table():
    src = (
        r'Before.' '\n\n'
        r'\begin{table}' '\n'
        r'\begin{tabular}{lc}' '\n'
        r'\toprule' '\n'
        r'H1 & H2 \\' '\n'
        r'\midrule' '\n'
        r'a & b \\' '\n'
        r'\bottomrule' '\n'
        r'\end{tabular}' '\n'
        r'\caption{Cap}' '\n'
        r'\label{tab:t1}' '\n'
        r'\end{table}' '\n\n'
        r'After.'
    )
    out = _process_text(src)
    # Original LaTeX table block is gone.
    assert r'\begin{table}' not in out
    assert r'\begin{tabular}' not in out
    # Single-line marker replaces it.
    assert '<!--TABLE payload=' in out
    # Surrounding prose preserved.
    assert 'Before.' in out
    assert 'After.' in out


@pytest.mark.skipif(not PANDOC_AVAILABLE, reason='pandoc not on PATH')
def test_process_text_round_trip_through_marker_to_myst():
    """Preprocess → marker → resolve_table_markers → MyST. The
    structural fidelity claim of #51: the table that pandoc would
    have collapsed (2 header rows separated by single ``\\hline``)
    survives intact."""
    src = (
        r'\begin{table}' '\n'
        r'\begin{tabular}{lccc}' '\n'
        r'\hline\hline' '\n'
        r'& Case I & Case II & Case III \\' '\n'
        r'& Ref1 & Ref2 & Ref3 \\' '\n'
        r'\hline' '\n'
        r'Regular & a & b & c \\' '\n'
        r'\hline\hline' '\n'
        r'\end{tabular}' '\n'
        r'\caption{Cap}' '\n'
        r'\label{tab:conv}' '\n'
        r'\end{table}'
    )
    out = _process_text(src)
    # Decode + emit.
    import re
    m = re.search(r'<!--TABLE payload=([A-Za-z0-9+/=]+)-->', out)
    assert m is not None
    from transforms.tables_from_latex import decode_marker, emit_myst, resolve_table_markers
    spec = decode_marker(m.group(1))
    # The KEY claim: 2 header rows survive (pandoc would have given 0).
    assert len(spec.header_rows) == 2
    assert len(spec.body_rows) == 1

    # Full resolver round-trip.
    resolved = resolve_table_markers(out)
    assert '````{table}' in resolved
    assert ':name: tab-conv' in resolved
    assert 'Cap' in resolved
    # Header_rows == 2 → falls back to {list-table} with :header-rows: 2.
    assert '```{list-table}' in resolved
    assert ':header-rows: 2' in resolved


@pytest.mark.skipif(not PANDOC_AVAILABLE, reason='pandoc not on PATH')
def test_process_text_no_op_for_pure_prose():
    """A source with no tabular-variant blocks at all must pass
    through unchanged — no spurious markers."""
    src = (
        r'Some prose with \textbf{bold}.' '\n\n'
        r'And a second paragraph with $math$ and \cref{tab:elsewhere}.'
    )
    out = _process_text(src)
    assert out == src
    assert '<!--TABLE' not in out


@pytest.mark.skipif(not PANDOC_AVAILABLE, reason='pandoc not on PATH')
def test_process_text_extracts_center_wrapped_tabular():
    """#55: ``\\begin{center}\\begin{tabular}...\\end{tabular}\\end{center}``
    is a common shape for non-float tables. The whole ``\\begin{center}``
    block is substituted (not just the tabular) so pandoc doesn't
    wrap the emitted MyST inside a ``::: center`` fenced div.

    Surfaced by Deep-Learning ``ch06_ha_youngs`` (9 histogram step
    tables in the worked example)."""
    src = (
        r'Walking through the steps:' '\n\n'
        r'\begin{center}\small' '\n'
        r'\begin{tabular}{l cccc c}' '\n'
        r'\toprule' '\n'
        r'& $k=1.0$ & $k=2.0$ & $k=3.0$ & $k=4.0$ & Row sum \\' '\n'
        r'\midrule' '\n'
        r'$\varepsilon=$low  & 0.10 & 0.20 & 0.10 & 0.05 & 0.45 \\' '\n'
        r'$\varepsilon=$high & 0.05 & 0.15 & 0.20 & 0.15 & 0.55 \\' '\n'
        r'\bottomrule' '\n'
        r'\end{tabular}' '\n'
        r'\end{center}' '\n'
        r'Then the next step:' '\n'
    )
    out = _process_text(src)
    assert '<!--TABLE' in out
    # The WHOLE \begin{center} block is replaced.
    assert r'\begin{center}' not in out
    assert r'\end{center}' not in out
    # Surrounding prose preserved.
    assert 'Walking through the steps' in out
    assert 'Then the next step' in out


@pytest.mark.skipif(not PANDOC_AVAILABLE, reason='pandoc not on PATH')
def test_process_text_extracts_tabularx_variant():
    """#55: ``\\begin{tabularx}{width}{colspec}`` is the flexible-width
    variant from the ``tabularx`` package. The width arg comes BEFORE
    the colspec — parser must skip it before reading column alignment.

    Surfaced by book-dp2 ``common_symbols.tex`` (3 notation-list
    tables wrapped in ``{\\setstretch{1.2}\\begin{tabularx}...}``).
    """
    src = (
        r'Notation:' '\n\n'
        r'\begin{tabularx}{\linewidth}{c || >{\raggedright\arraybackslash}X}' '\n'
        r'$\1\{P\}$ & indicator function \\' '\n'
        r'$\alpha$ & a scalar \\' '\n'
        r'\end{tabularx}' '\n'
    )
    out = _process_text(src)
    assert '<!--TABLE' in out
    # Original tabularx block gone.
    assert r'\begin{tabularx}' not in out


@pytest.mark.skipif(not PANDOC_AVAILABLE, reason='pandoc not on PATH')
def test_process_text_skips_tabular_inside_tikzpicture():
    """A ``\\begin{tabular}`` inside ``\\begin{tikzpicture}`` is part of
    a TikZ matrix node, NOT a real table. Extracting it would inject
    a ``{table}`` directive inside what mystmd treats as raw TikZ
    content — broken.

    Surfaced by Deep-Learning ``ch06_ha_youngs`` (1 tikzpicture with
    a tabular-shaped node)."""
    src = (
        r'\begin{tikzpicture}' '\n'
        r'\node[draw] (n1) at (0,0) {' '\n'
        r'\begin{tabular}{cc}' '\n'
        r'  a & b \\' '\n'
        r'\end{tabular}' '\n'
        r'};' '\n'
        r'\end{tikzpicture}' '\n'
    )
    out = _process_text(src)
    # No marker should be inserted — the tabular is inside TikZ.
    assert '<!--TABLE' not in out
    # Original tabular should remain unchanged.
    assert r'\begin{tabular}' in out


def test_parse_table_block_promotes_bold_title_paragraph_to_caption():
    """``\\textbf{X}\\par\\smallskip?`` immediately preceding
    ``\\begin{tabular}`` (optionally with intervening font-size or
    ``\\renewcommand`` config commands) is promoted to a synthetic
    caption when there's no explicit ``\\caption{}``.

    Surfaced by Deep-Learning ``execution_map`` (#59 was the original
    request; PR #60 retest flagged that #55 dropped the title
    entirely). Pre-#55 it stayed as orphaned bold prose above the
    table; #55 substituted the whole ``\\begin{center}`` block which
    silently deleted it. This promotion restores the title as the
    table's caption — the table becomes an enumerable container
    (with no ``\\label{}`` for cross-ref impact)."""
    body = (
        r'\begin{center}' '\n'
        r'\textbf{Execution map: chapters and notebooks}\par\smallskip' '\n'
        r'\scriptsize' '\n'
        r'\renewcommand{\arraystretch}{1.2}' '\n'
        r'\begin{tabular}{ll}' '\n'
        r'\hline' '\n'
        r'Ch & Topic \\' '\n'
        r'\hline' '\n'
        r'1 & Intro \\' '\n'
        r'\hline' '\n'
        r'\end{tabular}' '\n'
        r'\end{center}' '\n'
    )
    # Note: this exercises parse_table_block on the WHOLE inside of
    # the center wrap (what _CENTER_BLOCK_RE captures as group 1).
    # The promotion logic should treat the bold paragraph as a
    # caption since there's no \caption{}.
    inner = body[len(r'\begin{center}') + 1 : -len(r'\end{center}') - 1]
    spec = parse_table_block(inner)
    assert spec is not None
    assert spec.caption == 'Execution map: chapters and notebooks'


def test_parse_table_block_does_not_promote_when_explicit_caption_present():
    """If an explicit ``\\caption{}`` exists, the bold-title promotion
    is skipped — don't clobber the author's caption."""
    body = (
        r'\textbf{Some bold preamble}\par\smallskip' '\n'
        r'\begin{tabular}{ll}' '\n'
        r'\hline' '\n'
        r'A & B \\' '\n'
        r'\hline' '\n'
        r'1 & 2 \\' '\n'
        r'\hline' '\n'
        r'\end{tabular}' '\n'
        r'\caption{The real caption}' '\n'
    )
    spec = parse_table_block(body)
    # Explicit caption wins; bold preamble is NOT promoted.
    assert spec.caption == 'The real caption'


def test_parse_table_block_does_not_promote_when_intervening_prose():
    """The promotion requires the bold paragraph to be IMMEDIATELY
    before the tabular (only whitespace and config commands in
    between). Real prose between them means the bold isn't the
    de-facto title — leave it alone."""
    body = (
        r'\textbf{A heading}\par' '\n'
        r'Some intervening prose paragraph that makes this not a title.' '\n'
        r'\begin{tabular}{ll}' '\n'
        r'\hline' '\n'
        r'a & b \\' '\n'
        r'\hline' '\n'
        r'\end{tabular}' '\n'
    )
    spec = parse_table_block(body)
    # No promotion — intervening prose disqualifies.
    assert spec.caption is None


@pytest.mark.skipif(not PANDOC_AVAILABLE, reason='pandoc not on PATH')
def test_pandoc_batch_convert_strips_adjacency_artifact():
    """Pandoc inserts ``\\`<!-- -->\\`{=html}`` between adjacent
    inline-math + digit/letter tokens (``$\\times$9``,
    ``$>$50,000``) as a defensive separator. mystmd handles the
    adjacency natively so the artifact is pure noise. Strip it from
    every converted cell.

    Surfaced by PR #60 retest: 4 cells across 3 Deep-Learning files
    showed visible ``\\`<!-- -->\\`{=html}`` text in the rendered
    output."""
    mod = _load_marker_preprocessor()
    cells = [
        r'(c$\times$9)',
        r'$>$50,000 agents',
        r'$\sim$500',
        r'plain text',  # control — no artifact should appear
    ]
    out = mod._pandoc_batch_convert(cells)
    assert all('<!-- -->' not in c for c in out), (
        f'adjacency artifact leaked into output: {out!r}'
    )
    assert all('{=html}' not in c for c in out), (
        f'pandoc raw-html attribute leaked into output: {out!r}'
    )
    # Sanity: cells still contain the math content.
    assert '$\\times$' in out[0]
    assert '9' in out[0]
    assert '$>$' in out[1]
    assert '50,000' in out[1]


@pytest.mark.skipif(not PANDOC_AVAILABLE, reason='pandoc not on PATH')
def test_process_text_skips_table_float_inside_skip_ancestor():
    """``\\begin{table}`` floats are subject to the same
    skip-ancestor check as center-wraps and bare tabulars. Surfaced
    by Copilot review of PR #60: the original step-1 loop had no
    skip check, so e.g. ``\\begin{frame}\\begin{table}...\\end{table}``
    (a captioned table inside a Beamer slide) would be extracted
    and replaced by a marker even though ``frame`` is in the skip
    set. The audit found ~6 such occurrences across the
    Deep-Learning sources (slide files, not in the pipeline today —
    but the gap is real for any future source that mixes slide and
    manuscript content)."""
    src = (
        r'\begin{frame}' '\n'
        r'\begin{table}' '\n'
        r'\begin{tabular}{cc}' '\n'
        r'\hline' '\n'
        r'A & B \\' '\n'
        r'\hline' '\n'
        r'a & b \\' '\n'
        r'\hline' '\n'
        r'\end{tabular}' '\n'
        r'\caption{Cap}' '\n'
        r'\label{tab:foo}' '\n'
        r'\end{table}' '\n'
        r'\end{frame}' '\n'
    )
    out = _process_text(src)
    # No marker — frame is a skip-set ancestor, so the table float
    # inside it is left for pandoc to handle.
    assert '<!--TABLE' not in out
    # Original LaTeX preserved.
    assert r'\begin{table}' in out


@pytest.mark.skipif(not PANDOC_AVAILABLE, reason='pandoc not on PATH')
def test_process_text_passes_through_tabu_variant():
    """``\\begin{tabu}`` is intentionally NOT recognised as a tabular
    variant by ``_TABULAR_OPEN_RE`` — the tabu package's syntax is
    too variable (``\\begin{tabu}{cols}``, ``\\begin{tabu} to <len>
    {cols}``, ``\\begin{tabu} spread <len> {cols}``) for the
    balanced-brace extractor to handle generically. A ``\\begin{tabu}``
    block must pass through the preprocessor unchanged so pandoc /
    ``convert_simple_tables`` can take a shot at it.

    Surfaced by Copilot review of PR #60. None of the test corpora
    use ``\\begin{tabu}`` so this is purely a defensive guarantee."""
    src = (
        r'\begin{tabu}{cc}' '\n'
        r'a & b \\' '\n'
        r'\end{tabu}' '\n'
    )
    out = _process_text(src)
    # No marker emitted — tabu is not in the recognised set.
    assert '<!--TABLE' not in out
    # Original LaTeX preserved unchanged.
    assert r'\begin{tabu}' in out


@pytest.mark.skipif(not PANDOC_AVAILABLE, reason='pandoc not on PATH')
def test_process_text_skips_tabular_with_deep_skip_ancestor():
    """A tabular's NEAREST ancestor may be safe (``center``) but a
    deeper wrapper (``frame``, ``tikzpicture``, etc.) may be in the
    skip set. The check must walk the WHOLE stack, not just the
    nearest. Surfaced by source files that mix Beamer slide content
    (``\\begin{frame}\\begin{center}\\begin{tabular}``) with
    manuscript content."""
    src = (
        r'\begin{frame}' '\n'
        r'\begin{center}' '\n'
        r'\begin{tabular}{cc}' '\n'
        r'  a & b \\' '\n'
        r'\end{tabular}' '\n'
        r'\end{center}' '\n'
        r'\end{frame}' '\n'
    )
    out = _process_text(src)
    # No marker — frame is a skip-set ancestor even though the
    # nearest is center.
    assert '<!--TABLE' not in out


@pytest.mark.skipif(not PANDOC_AVAILABLE, reason='pandoc not on PATH')
def test_process_text_skips_tabular_inside_math_env():
    """A ``\\begin{tabular}`` inside a math environment is matrix-like
    math content (rare but possible). Extracting it would produce a
    ``{table}`` directive inside a ``\\begin{equation}`` block,
    which mystmd would misinterpret. Defensive: skip via the
    ancestor-env list."""
    src = (
        r'\begin{equation}' '\n'
        r'\begin{tabular}{cc}' '\n'
        r'  a & b \\' '\n'
        r'\end{tabular}' '\n'
        r'\end{equation}' '\n'
    )
    out = _process_text(src)
    assert '<!--TABLE' not in out


@pytest.mark.skipif(not PANDOC_AVAILABLE, reason='pandoc not on PATH')
def test_process_text_extracts_bare_tabular():
    """#55: bare ``\\begin{tabular}`` (no ``\\begin{table}`` wrapper)
    is now extracted by the marker preprocessor. Previously these
    fell through to ``convert_simple_tables`` (the pandoc-output
    path); the unified path eliminates the parallel handling."""
    src = (
        r'Some prose with \textbf{bold}.' '\n\n'
        r'\begin{tabular}{ll}' '\n'
        r'\hline' '\n'
        r'H1 & H2 \\' '\n'
        r'\hline' '\n'
        r'a & b \\' '\n'
        r'\hline' '\n'
        r'\end{tabular}'
    )
    out = _process_text(src)
    assert '<!--TABLE' in out
    # Original \begin{tabular} block is gone, replaced by the marker.
    assert r'\begin{tabular}' not in out
    # Surrounding prose preserved.
    assert 'Some prose with' in out


@pytest.mark.skipif(not PANDOC_AVAILABLE, reason='pandoc not on PATH')
def test_process_text_converts_inline_latex_in_cells_via_pandoc():
    """Cells containing ``\\textbf{}``, ``\\ref{}``, ``$math$`` etc.
    are converted to markdown via the batched pandoc invocation. The
    marker payload contains markdown cells, not raw LaTeX."""
    src = (
        r'\begin{table}' '\n'
        r'\begin{tabular}{ll}' '\n'
        r'\toprule' '\n'
        r'\textbf{Symbol} & \textbf{Meaning} \\' '\n'
        r'\midrule' '\n'
        r'$x$ & state \\' '\n'
        r'$y$ & action \\' '\n'
        r'\bottomrule' '\n'
        r'\end{tabular}' '\n'
        r'\caption{Notation}' '\n'
        r'\label{tab:nt}' '\n'
        r'\end{table}'
    )
    out = _process_text(src)
    import re
    m = re.search(r'<!--TABLE payload=([A-Za-z0-9+/=]+)-->', out)
    from transforms.tables_from_latex import decode_marker
    spec = decode_marker(m.group(1))
    # Cells are markdown, not raw LaTeX.
    assert spec.header_rows[0] == ['**Symbol**', '**Meaning**']
    assert spec.body_rows[0] == ['$x$', 'state']
    assert spec.caption == 'Notation'


def test_resolve_table_markers_leaves_corrupted_payload_in_place():
    """A corrupted marker payload (malformed base64, valid base64 of
    non-JSON, JSON with wrong shape) must NOT crash the postprocess
    pipeline. The original marker is left in the text so the failure
    is visible to the author. Mirrors ``resolve_algorithms``'s
    defensive decode pattern. Surfaced by Copilot review of PR #53."""
    from transforms.tables_from_latex import resolve_table_markers

    # Three corruption modes: invalid base64, valid base64 of non-JSON,
    # JSON with missing required fields. All should pass through.
    for payload in ('not-base64-!!!', 'bm90LWpzb24=', 'eyJmb28iOiJiYXIifQ=='):
        text = f'Before.\n\n<!--TABLE payload={payload}-->\n\nAfter.'
        out = resolve_table_markers(text)
        assert 'Before.' in out
        assert 'After.' in out
        # Original marker preserved on failure.
        assert f'<!--TABLE payload={payload}-->' in out


def test_resolve_table_markers_decodes_in_place():
    """``resolve_table_markers`` finds markers in pandoc-emitted text
    (where ``<`` is escaped to ``\\<``) and replaces them with the
    emitted MyST directive."""
    from transforms.tables_from_latex import (
        TableSpec,
        encode_marker,
        resolve_table_markers,
    )

    spec = TableSpec(
        name='tab-foo',
        caption='Caption.',
        colspec=['l', 'c'],
        header_rows=[['H1', 'H2']],
        body_rows=[['a', 'b']],
    )
    marker = encode_marker(spec)

    # Simulate pandoc's escape behaviour: ``<`` → ``\<``, ``>`` → ``\>``.
    pandoc_emitted = marker.replace('<', r'\<').replace('>', r'\>')
    text = f'Before.\n\n{pandoc_emitted}\n\nAfter.'

    out = resolve_table_markers(text)
    assert 'Before.' in out
    assert 'After.' in out
    assert '````{table}' in out
    assert ':name: tab-foo' in out
    assert '| H1 | H2 |' in out
    assert '| a | b |' in out
    # Marker is gone.
    assert '<!--TABLE' not in out
    assert r'\<!--TABLE' not in out
