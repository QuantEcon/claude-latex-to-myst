"""Tests for the structural validator counts in scripts/validate.py.

These guard the three classes of false-positive `!` markers the
validator used to emit (GH #14, #15, #16).
"""

from __future__ import annotations

import pytest

import validate as v


# ── #14: commented-out LaTeX envs must not be counted ────────────────────────


def test_strip_latex_comments_removes_full_line_comment():
    assert v._strip_latex_comments("% all gone\nkept\n") == "\nkept\n"


def test_strip_latex_comments_keeps_mid_line_trailing_comment():
    """``\\begin{lemma} % TODO`` is a live env with a trailing note —
    must survive the strip so the env still counts."""
    text = r"\begin{lemma} % TODO\end{lemma}"
    assert v._strip_latex_comments(text) == text


def test_strip_latex_comments_handles_leading_whitespace():
    """Indented comment lines are still whole-line comments."""
    assert v._strip_latex_comments("    % indented\nkept\n") == "\nkept\n"


def test_count_latex_theorems_skips_commented_block():
    """GH #14 reproduction: a commented `\\begin{lemma}` line must not
    bump the theorems count."""
    tex = (
        r"\begin{lemma}\label{a}body\end{lemma}" "\n"
        r"% \begin{lemma}\label{b}body\end{lemma}" "\n"
        r"\begin{theorem}\label{c}body\end{theorem}" "\n"
    )
    assert v.count_latex(tex)['theorems'] == 2


# ── #15: figures subfigure-aware count ───────────────────────────────────────


def test_count_figures_plain_figure_counts_one():
    tex = r"\begin{figure}\includegraphics{x}\caption{c}\end{figure}"
    assert v.count_latex(tex)['figures'] == 1


def test_count_figures_figure_with_two_subfigures_counts_two():
    """GH #15: pipeline emits one ``{figure}`` per ``\\begin{subfigure}``;
    the outer ``\\begin{figure}`` wrapper is discarded."""
    tex = (
        r"\begin{figure}" "\n"
        r"  \begin{subfigure}\caption{a}\end{subfigure}" "\n"
        r"  \begin{subfigure}\caption{b}\end{subfigure}" "\n"
        r"  \caption{outer}" "\n"
        r"\end{figure}" "\n"
    )
    assert v.count_latex(tex)['figures'] == 2


def test_count_figures_mixed_figures_and_subfigures():
    """Reporter's dp2 ch_adps shape: 4 figures, 2 of them with 2
    subfigures each → 4 + 2 = 6 MyST figures."""
    block_with_subs = (
        r"\begin{figure}" "\n"
        r"  \begin{subfigure}\caption{a}\end{subfigure}" "\n"
        r"  \begin{subfigure}\caption{b}\end{subfigure}" "\n"
        r"\end{figure}" "\n"
    )
    plain = r"\begin{figure}\includegraphics{x}\end{figure}" "\n"
    tex = block_with_subs * 2 + plain * 2
    assert v.count_latex(tex)['figures'] == 6


# ── Phase 6: marker-aware counting for split-source books ────────────────────
# ``validate`` reads the *preprocessed* tmp file for ``preprocess.split:``
# books (e.g. Deep-Learning), where figures/citations are already markers.
# Counting must see through the markers or it under-counts the source (a
# measurement artifact — the markdown is faithful).

def test_count_figures_counts_figure_markers():
    """A ``<!--FIGURE payload=…-->`` marker (preprocessed figure) counts as a
    figure, alongside any raw ``\\begin{figure}`` blocks."""
    from transforms.figures_from_latex import FigureSpec, encode_marker
    marker = encode_marker(FigureSpec(name='f-x', caption='C'))
    tex = marker + "\n\n" + r"\begin{figure}\includegraphics{y}\end{figure}" "\n"
    assert v.count_latex(tex)['figures'] == 2


def test_count_figures_marker_honours_subfigure_panels():
    """A subfigure-float marker counts as N (one per panel)."""
    from transforms.figures_from_latex import FigureSpec, encode_marker
    spec = FigureSpec(name='f-x', subfigures=[
        {'name': None, 'caption': 'a', 'image_src': 'a.pdf', 'width': None},
        {'name': None, 'caption': 'b', 'image_src': 'b.pdf', 'width': None},
    ])
    assert v.count_latex(encode_marker(spec))['figures'] == 2


def test_count_citations_counts_natbib_markers():
    """``[[CITEP:…]]`` / ``[[CITEALT:…]]`` markers (preprocessed natbib) count
    as citations alongside raw ``\\cite…`` commands."""
    tex = r"\citet{a} and [[CITEP:b,c]] and [[CITEALT:d]]." "\n"
    assert v.count_latex(tex)['citations'] == 3


# ── #16: MyST equation count includes labeled-close fences ───────────────────


def test_count_myst_equations_unlabeled_block():
    md = "intro\n$$\n  x = y\n$$\nouter\n"
    assert v.count_myst(md)['equations'] == 1


def test_count_myst_equations_labeled_block():
    """GH #16: ``$$ (eq-foo)`` is the close fence of a labeled block; the
    old regex matched only the open, leaving 1 lonely fence → //2 = 0."""
    md = "intro\n$$\n  x = y\n$$ (eq-foo)\nouter\n"
    assert v.count_myst(md)['equations'] == 1
    assert v.count_myst(md)['labeled_eqs'] == 1


@pytest.mark.parametrize("n_unlabeled,n_labeled", [
    (0, 0), (3, 0), (0, 3), (2, 5), (1, 1),
])
def test_count_myst_equations_mixed_totals(n_unlabeled, n_labeled):
    md = (
        "$$\n  a = b\n$$\n" * n_unlabeled
        + "$$\n  c = d\n$$ (eq-x)\n" * n_labeled
    )
    assert v.count_myst(md)['equations'] == n_unlabeled + n_labeled
    assert v.count_myst(md)['labeled_eqs'] == n_labeled


# ── Citation counters (#67) ──────────────────────────────────────────────────


def test_count_latex_citations_all_natbib_variants():
    """Every ``\\cite*`` variant the pipeline rewrites must be counted on
    the LaTeX side. Pre-fix the narrow ``\\cite[pt]?\\{`` form caught
    only three of the eight variants, leaving the other five
    invisible to the validator and creating a phantom under-count on
    the LaTeX side."""
    tex = (
        r"See \cite{a} and \citet{b} and \citep{c} and "
        r"\citealp{d} and \citealt{e} and \citeauthor{f} and "
        r"\citeyear{g} and \citeyearpar{h}."
    )
    # All 8 forms counted (one each).
    assert v.count_latex(tex)['citations'] == 8


def test_count_myst_citations_all_roles():
    """``count_myst`` must match every ``{cite:*}`` role the pipeline
    emits, not just ``{cite}`` / ``{cite:t}``. The previous narrow
    regex missed ``{cite:p}`` (the ``\\citep`` form), ``{cite:author}``,
    and ``{cite:year}`` — see #67 for the dp1 reproducer where four
    chapters under-counted by one each."""
    md = (
        "{cite}`a` and {cite:t}`b` and {cite:p}`c` and "
        "{cite:author}`d` and {cite:year}`e`."
    )
    # All 5 roles counted (one each).
    assert v.count_myst(md)['citations'] == 5


def test_count_latex_citations_with_optional_args():
    """Natbib ``\\cite*`` variants accept 0-2 optional ``[prenote][postnote]``
    args between the command and the key (``\\citep[see][ch. 2]{key}``).
    Pre-fix the regex required ``{`` immediately after the command name
    so every optional-arg cite was under-counted, producing phantom
    LaTeX↔MyST mismatches in books that use them (1 instance in
    book-dp1, 1 in book-dp2, 28 in the Deep_Learning corpus). Mirrors
    ``_NATBIB_OPT`` in ``scripts/_apply_rewrites.py``."""
    tex = (
        r"\citep[see][ch.~2]{a} and "      # two optional args
        r"\citep[e.g.,][]{b} and "         # one filled + one empty
        r"\citet[\S 7.5]{c} and "          # single optional
        r"\citep{d}"                       # no optional
    )
    assert v.count_latex(tex)['citations'] == 4


def test_citation_counts_balance_natbib_round_trip():
    """End-to-end fairness — for every natbib variant the pipeline
    rewrites to a ``{cite:*}`` role, the LaTeX count and the MyST
    count must agree. Catches the kind of asymmetry that surfaced in
    #67 where ``\\citep`` was counted on the LaTeX side but not on
    the MyST side."""
    cases = [
        (r"\cite{k}",         "{cite}`k`"),
        (r"\citet{k}",        "{cite:t}`k`"),
        (r"\citep{k}",        "{cite:p}`k`"),
        (r"\citealp{k}",      "{cite:t}`k`"),      # routes to {cite:t}
        (r"\citealt{k}",      "{cite:t}`k`"),      # routes to {cite:t}
        (r"\citeauthor{k}",   "{cite:author}`k`"),
        (r"\citeyear{k}",     "{cite:year}`k`"),
        (r"\citeyearpar{k}",  "{cite:year}`k`"),   # routes to {cite:year}
    ]
    tex = ' '.join(t for t, _ in cases)
    md = ' '.join(m for _, m in cases)
    assert v.count_latex(tex)['citations'] == v.count_myst(md)['citations']


# ── Cross-reference resolution check (P1a) ───────────────────────────────────


def test_collect_anchors_standalone_target():
    """``(name)=`` on its own line is the standard standalone-label form."""
    md = "intro\n(eq-mse)=\n$$\nx=y\n$$\nouter\n"
    assert 'eq-mse' in v.collect_anchors(md)


def test_collect_anchors_directive_name_option():
    """``:name: X`` inside a directive (figure, code-block, etc.)."""
    md = "```{figure} path.png\n:name: fig-foo\n\nCaption.\n```\n"
    assert 'fig-foo' in v.collect_anchors(md)


def test_collect_anchors_directive_label_option():
    """``:label: X`` (sphinx-proof prf directives use this form)."""
    md = "```{prf:theorem}\n:label: thm-main\n\nBody.\n```\n"
    assert 'thm-main' in v.collect_anchors(md)


def test_collect_anchors_heading_auto_id():
    """``# Title {#slug}`` heading auto-id syntax."""
    md = "# Introduction {#intro}\n\nBody.\n"
    assert 'intro' in v.collect_anchors(md)


def test_collect_anchors_heading_auto_id_with_classes():
    """``# Title {#slug .unnumbered}`` — classes after the slug must not
    leak into the anchor name (lesson 017)."""
    md = "# Preface {#preface .unnumbered .unlisted}\n\nBody.\n"
    assert v.collect_anchors(md) == {'preface'}


def test_collect_anchors_frontmatter_label():
    """``label: foo`` in YAML frontmatter is a chapter-level anchor."""
    md = "---\ntitle: Foo\nlabel: ch-foo\n---\n\nBody.\n"
    assert 'ch-foo' in v.collect_anchors(md)


def test_collect_anchors_trailing_paren_equation_label():
    """``$$ (eq-foo)`` close fence carries the block's anchor."""
    md = "$$\nx = y\n$$ (eq-foo)\n\nbody\n"
    assert 'eq-foo' in v.collect_anchors(md)


def test_collect_anchors_finds_multiple_in_one_doc():
    """A real chapter has several anchor forms intermixed."""
    md = (
        "---\nlabel: ch-main\n---\n\n"
        "# Section {#sec-one}\n\n"
        "(eq-foo)=\n$$\nx=y\n$$\n\n"
        "```{prf:theorem}\n:label: thm-main\n\nBody\n```\n"
    )
    anchors = v.collect_anchors(md)
    assert anchors == {'ch-main', 'sec-one', 'eq-foo', 'thm-main'}


def test_collect_references_xref_roles():
    """{ref}, {eq}, {numref}, {prf:ref} all register as cross-refs."""
    md = "See {ref}`sec-a`, {eq}`eq-b`, {numref}`fig-c`, {prf:ref}`thm-d`."
    xrefs, cites = v.collect_references(md)
    assert xrefs == {'sec-a', 'eq-b', 'fig-c', 'thm-d'}
    assert cites == set()


def test_collect_references_cite_roles():
    """{cite}, {cite:t}, {cite:p}, {cite:author}, {cite:year} all
    register as citations."""
    md = ("Refs: {cite}`a`, {cite:t}`b`, {cite:p}`c`, "
          "{cite:author}`d`, {cite:year}`e`.")
    _, cites = v.collect_references(md)
    assert cites == {'a', 'b', 'c', 'd', 'e'}


def test_collect_references_multi_key_cite_split():
    """``{cite}`a,b,c``` is a multi-key citation; each key separately."""
    md = "See {cite}`smith2020,jones2019,brown2018`."
    _, cites = v.collect_references(md)
    assert cites == {'smith2020', 'jones2019', 'brown2018'}


def test_collect_references_does_not_split_xref():
    """Cross-refs never carry comma-separated targets — single name only."""
    md = "See {ref}`sec-one`."
    xrefs, _ = v.collect_references(md)
    assert xrefs == {'sec-one'}


def test_check_resolution_clean_returns_empty():
    """Every reference resolves; diagnostics empty."""
    md = "(eq-foo)=\n$$\nx=y\n$$\n\nSee {eq}`eq-foo`.\n"
    assert v.check_resolution(md, 'x.md') == []


def test_check_resolution_flags_missing_anchor():
    """A {ref} to an anchor that isn't declared anywhere is unresolved."""
    md = "See {eq}`eq-missing`.\n"
    diags = v.check_resolution(md, 'ch01.md')
    assert len(diags) == 1
    assert 'unresolved cross-reference' in diags[0]
    assert 'eq-missing' in diags[0]


def test_check_resolution_flags_missing_bib_key():
    """A {cite} to a key not in the bib is unresolved."""
    md = "Per {cite:t}`unknown_key`.\n"
    diags = v.check_resolution(md, 'ch01.md', bib_keys={'known_key'})
    assert len(diags) == 1
    assert 'unresolved citation' in diags[0]
    assert 'unknown_key' in diags[0]


def test_check_resolution_skips_cite_check_when_no_bib():
    """If bib_keys is None (no bibliography configured), citation
    resolution is not enforced — only cross-refs."""
    md = "See {cite:t}`anykey`.\n"
    assert v.check_resolution(md, 'x.md', bib_keys=None) == []


def test_check_resolution_known_broken_shape_from_issue_30():
    """Regression test against the #30 shape: an align block's per-row
    label was lost, leaving the ``{eq}`` reference to nothing. The new
    pipeline produces ``(eq-X)=`` anchors; this confirms validate
    would now flag a pre-#30 output (anchor missing, ref present)."""
    pre_fix_output = (
        "$$\n"
        "\\begin{aligned}\n"
        "a &= b, \\label{eq:foo}\\\\\n"
        "c &= d.\n"
        "\\end{aligned}\n"
        "$$\n\n"
        "See {eq}`eq-foo` later.\n"
    )
    diags = v.check_resolution(pre_fix_output, 'ch.md')
    assert any('eq-foo' in d for d in diags)


def test_parse_bib_keys_simple(tmp_path):
    """Parse a minimal .bib file."""
    bib = tmp_path / 'refs.bib'
    bib.write_text(
        '@book{smith2020,\n  title = {Title},\n  author = {Smith},\n}\n'
        '@article{jones2019,\n  title = {Other},\n}\n'
    )
    assert v.parse_bib_keys(bib) == {'smith2020', 'jones2019'}


def test_parse_bib_keys_colon_bearing(tmp_path):
    """JabRef/Mendeley/ACM-style colon-bearing keys parse correctly
    (lesson 031)."""
    bib = tmp_path / 'refs.bib'
    bib.write_text(
        '@inproceedings{Bertsekas:2000:DPO:517430,\n  title = {DP},\n}\n'
        '@article{ECTA:ECTA1716,\n  title = {Article},\n}\n'
    )
    assert v.parse_bib_keys(bib) == {
        'Bertsekas:2000:DPO:517430', 'ECTA:ECTA1716',
    }


def test_parse_bib_keys_missing_file(tmp_path):
    """Missing .bib file returns empty set, no crash."""
    assert v.parse_bib_keys(tmp_path / 'nonexistent.bib') == set()


def test_parse_bib_keys_ignores_strings_and_preamble(tmp_path):
    """``@string{...}`` and ``@preamble{...}`` are not citation keys —
    they're bib-file directives. The bare key regex would match them;
    in practice they're rare and harmless (no citation would target
    them either). Documented here so future tightening is explicit."""
    bib = tmp_path / 'refs.bib'
    bib.write_text(
        '@string{j = "Journal"}\n'
        '@article{realkey,\n  title = {x},\n}\n'
    )
    # Both match the current parser. ``realkey`` is the real one.
    keys = v.parse_bib_keys(bib)
    assert 'realkey' in keys


# ── Type-compatibility check (P1a-prime, closes #38 class) ───────────────────


def test_collect_typed_references_captures_role():
    """``collect_typed_references`` returns (role, target) pairs for
    every cross-reference, plus the same cite-key set as
    ``collect_references``."""
    md = (
        "See {ref}`sec-a`, {eq}`eq-b`, {numref}`fig-c`, "
        "{prf:ref}`thm-d`, {cite:t}`smith2020`."
    )
    typed_xrefs, cites = v.collect_typed_references(md)
    assert ('ref',     'sec-a')  in typed_xrefs
    assert ('eq',      'eq-b')   in typed_xrefs
    assert ('numref',  'fig-c')  in typed_xrefs
    assert ('prf:ref', 'thm-d')  in typed_xrefs
    assert cites == {'smith2020'}


def test_check_resolution_flags_directive_type_mismatch():
    """A ``{ref}`eq-foo`` that resolves to an existing eq anchor is
    still broken in MyST — equation anchors are only reachable via
    ``{eq}``. The type-compatibility check (P1a-prime) flags it."""
    # ``eq-foo`` exists (trailing-paren equation label form), and
    # something references it via plain ``{ref}``. Anchor resolves
    # by name; type does NOT match.
    md = "$$\nx = y\n$$ (eq-foo)\n\nSee {ref}`eq-foo`.\n"
    diags = v.check_resolution(md, 'ch.md')
    assert any('directive-type mismatch' in d and 'eq-foo' in d for d in diags), diags
    assert any('expects {eq}' in d for d in diags), diags


def test_check_resolution_flags_ref_to_prf_anchor():
    """``{ref}`alg-young`` cannot target a ``{prf:algorithm}``
    directive's ``:label:``. Should be ``{prf:ref}``."""
    md = (
        "```{prf:algorithm}\n:label: alg-young\n\nBody\n```\n"
        "\nLater, see {ref}`alg-young`.\n"
    )
    diags = v.check_resolution(md, 'ch.md')
    assert any('directive-type mismatch' in d and 'alg-young' in d for d in diags), diags


def test_check_resolution_no_mismatch_when_role_matches():
    """Well-typed refs produce no diagnostics."""
    md = (
        "$$\nx = y\n$$ (eq-foo)\n\n"
        "```{prf:theorem}\n:label: thm-main\n\nBody\n```\n\n"
        "# Section {#sec-a}\n\n"
        "See {eq}`eq-foo`, {prf:ref}`thm-main`, {ref}`sec-a`.\n"
    )
    assert v.check_resolution(md, 'ch.md') == []


def test_check_resolution_skips_type_check_when_disabled():
    """``check_types=False`` opts out of the type-compatibility pass.
    Only name resolution remains."""
    md = "$$\nx = y\n$$ (eq-foo)\n\nSee {ref}`eq-foo`.\n"
    diags = v.check_resolution(md, 'ch.md', check_types=False)
    # Name resolves, type check skipped → no diagnostics.
    assert diags == []


def test_check_resolution_unresolved_name_does_not_emit_type_mismatch():
    """When the name doesn't resolve, the type-mismatch pass is
    skipped for that target (would be noise on top of the bigger
    "missing anchor" problem)."""
    md = "See {ref}`eq-missing`.\n"
    diags = v.check_resolution(md, 'ch.md')
    assert any('unresolved' in d for d in diags)
    assert not any('directive-type mismatch' in d for d in diags)


def test_check_resolution_section_ref_passes():
    """Generic ``{ref}`` to section-family labels is the right
    directive type — regression guard for the routing table."""
    md = "# Intro {#sec-intro}\n\nSee {ref}`sec-intro`.\n"
    assert v.check_resolution(md, 'ch.md') == []


def test_check_resolution_numref_to_figure_passes():
    """``{numref}`fig-X`` is the right directive type for figure
    anchors — regression guard."""
    md = (
        "```{figure} fig.png\n:name: fig-bar\n\nCaption\n```\n\n"
        "See {numref}`fig-bar`.\n"
    )
    assert v.check_resolution(md, 'ch.md') == []


# ── main() end-to-end (#68 preprocess.split: blindspot) ──────────────────────
#
# These shell out to ``validate.py`` because the bug lives in ``main()`` —
# specifically the per-chapter loop's source-``.tex`` resolution and the
# vacuous-pass branch at the bottom. Unit-testing the counter helpers
# (above) won't surface either failure mode.


import subprocess  # noqa: E402
import sys  # noqa: E402
from pathlib import Path  # noqa: E402


_VALIDATE = Path(__file__).resolve().parent.parent / "scripts" / "validate.py"


def _run_validate(config: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(_VALIDATE), "--config", str(config)],
        capture_output=True,
        text=True,
    )


def _layout_split_book(tmp_path: Path) -> Path:
    """Set up a minimal ``preprocess.split:``-style book under
    ``tmp_path``. The pristine source contains a monolithic ``.tex``;
    the per-chapter ``.tex`` files live only in ``tmp_dir`` (where
    ``preprocess.sh`` would have written them). Returns the config
    path."""
    src = tmp_path / "src"
    out = tmp_path / "out"
    tmp = tmp_path / "tmp"
    src.mkdir()
    out.mkdir()
    tmp.mkdir()

    # Monolithic source — exists in src/ but no per-stem files there.
    (src / "monolith.tex").write_text("\\chapter{Intro}\n", encoding="utf-8")

    # Per-stem split outputs in tmp/ (where preprocess.sh would write them).
    (tmp / "ch_a.tex").write_text(
        "\\chapter{A}\n\\cite{x}\n", encoding="utf-8"
    )

    # Converted markdown in output_dir.
    (out / "ch_a.md").write_text(
        "# A\n\n{cite}`x`\n", encoding="utf-8"
    )

    config = tmp_path / "config.yaml"
    config.write_text(
        "source_dir: ./src\n"
        "output_dir: ./out\n"
        "tmp_dir: ./tmp\n"
        "chapters:\n"
        "  - { stem: ch_a, title: A }\n",
        encoding="utf-8",
    )
    return config


def test_validate_falls_back_to_tmp_dir_for_split_books(tmp_path):
    """GH #68 — when a chapter's ``.tex`` lives in ``tmp_dir`` (because
    ``preprocess.split:`` fans the monolithic source out there) the
    validator must find it. Pre-fix the per-chapter loop silently
    skipped every stem on books that use ``preprocess.split:``."""
    config = _layout_split_book(tmp_path)
    result = _run_validate(config)
    assert result.returncode == 0, (
        f"validate exited {result.returncode}\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )
    # The chapter row appears in the table — the loop actually ran.
    assert "ch_a" in result.stdout
    assert "All counts match" in result.stdout
    # No vacuous-pass error.
    assert "no chapters were validated" not in result.stderr


def test_validate_warns_when_tex_truly_missing(tmp_path):
    """GH #68 — when a stem's ``.tex`` is missing from BOTH
    ``source_dir`` and ``tmp_dir`` the validator must emit a WARN
    (not silently skip) so the regression class can't recur unseen."""
    src = tmp_path / "src"
    out = tmp_path / "out"
    tmp = tmp_path / "tmp"
    src.mkdir(); out.mkdir(); tmp.mkdir()

    # Only the .md exists — .tex is missing everywhere.
    (out / "ch_b.md").write_text("# B\n", encoding="utf-8")

    config = tmp_path / "config.yaml"
    config.write_text(
        "source_dir: ./src\n"
        "output_dir: ./out\n"
        "tmp_dir: ./tmp\n"
        "chapters:\n"
        "  - { stem: ch_b, title: B }\n",
        encoding="utf-8",
    )
    result = _run_validate(config)
    assert "ch_b.tex not found" in result.stderr, (
        f"Expected WARN about missing .tex, got:\n{result.stderr}"
    )


def test_validate_vacuous_pass_guard_exits_nonzero(tmp_path):
    """GH #68 — when every chapter is skipped (so ``validated_count == 0``)
    the validator must NOT print "All counts match" and must exit
    non-zero. Pre-fix it printed a happy success message under those
    conditions, masking the real problem."""
    src = tmp_path / "src"
    out = tmp_path / "out"
    tmp = tmp_path / "tmp"
    src.mkdir(); out.mkdir(); tmp.mkdir()

    # Stem listed in config but neither .tex nor .md present.
    config = tmp_path / "config.yaml"
    config.write_text(
        "source_dir: ./src\n"
        "output_dir: ./out\n"
        "tmp_dir: ./tmp\n"
        "chapters:\n"
        "  - { stem: ch_missing, title: M }\n",
        encoding="utf-8",
    )
    result = _run_validate(config)
    assert result.returncode != 0, (
        f"Expected non-zero exit when nothing validated, got 0\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )
    assert "no chapters were validated" in result.stderr
    assert "All counts match" not in result.stdout


def test_count_myst_equations_math_directive():
    """Starred displays emit ```{math} directives (#113) — count them as
    equations so a starred env doesn't read as a drop (dp1 parity run)."""
    md = (
        "```{math}\n:enumerated: false\n\nx = 1\n```\n\n"
        "$$\ny = 2\n$$\n"
    )
    assert v.count_myst(md)['equations'] == 2


def test_backtick_in_fence_info_string_flagged():
    """#122: CommonMark forbids backticks in a backtick-fence info string —
    the directive never opens and its closer swallows following content.
    validate must flag the emission so the class is caught in CI."""
    md = "```{prf:proof} Proof of {prf:ref}`p-x`\nBody.\n```\n"
    diags = v.check_resolution(md, 'f.md', bib_keys=None)
    assert any('backtick in backtick-fence info string' in d for d in diags)
    clean = "```{prf:proof} Proof of the main result\nBody.\n```\n"
    assert not any('info string' in d
                   for d in v.check_resolution(clean, 'f.md', bib_keys=None))


def test_backtick_in_indented_fence_info_string_flagged():
    """CommonMark allows fences indented up to 3 spaces (e.g. a directive
    nested in a list item) — the info-string check must catch those too."""
    md = "- item\n\n  ```{prf:proof} Proof of {prf:ref}`p-x`\n  Body.\n  ```\n"
    diags = v.check_resolution(md, 'f.md', bib_keys=None)
    assert any('backtick in backtick-fence info string' in d for d in diags)


def test_build_smoke_normalize():
    """build_smoke normalization folds run-specific noise (hashes, temp
    dirs, numbers) so two builds of identical content compare equal."""
    import build_smoke as bs
    log = (
        "📖 Built ch_intro.md in 3.33 s.\n"
        "⚠️  ch_mdps.md:10 label \"sss-fsmdp\" replaced with \"ss-gfsmdp\"\n"
        "⛔️ ch_x.md Cannot find image \"fig/foo_12.pdf\" in /private/tmp/build-xyz\n"
        "⚠️  _build/site/public/nrm_sk-ae78155e96e799fa.png Image is too large (2.29 MB)\n"
    )
    out = bs.normalize(log)
    assert len(out) == 3                      # the Built line is not a marker
    assert 'ch_mdps.md:N label "sss-fsmdp" replaced with "ss-gfsmdp"' in out
    assert any('TMPDIR' in l for l in out)
    assert any('-HASH.png' in l for l in out)
    # determinism: same input → same output
    assert bs.normalize(log) == out
