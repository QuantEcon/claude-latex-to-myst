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
