"""§1b differential migration-parity gate (Phase 1 — see
``notes/design/phase-1-validation-gate.md`` §1b; lesson 044).

A *golden* corpus catches regressions against a frozen ``expected.md``. The
subtler failure mode — the one that produced all four GH #98 regressions — is
**migrating a construct from its HTML-fallback path to a marker path silently
dropping a feature the old path had**. At migration time there is no "before"
to diff against, and the author writes ``expected.md`` from the new (buggy)
path's output, so the golden tier blesses the regression.

This module is the antidote: run *both* paths over a corpus of real ``.tex``
blocks and assert the marker (new) path is **equal-or-better** — never loses a
feature the fallback (old) path produced.

  - **fallback path:** pandoc emits an HTML ``<figure>``; ``process_text``'s
    ``convert_html_figures`` resolves it. (Reproduced here by running the
    pipeline with the figure-marker preprocessor *disabled*.)
  - **marker path:** ``_apply_figure_markers.py`` extracts the float
    pre-pandoc; ``resolve_figure_markers`` decodes it post-pandoc. (The
    default pipeline.)

Phase 1 builds the scaffold and proves it runs over the corpus. **Phase 4**
exercises it for real: when ``_apply_figure_markers`` learns ``subfigure``
(#94), this gate proves the marker output is equal-or-better than the
fallback before the fallback is retired and the snapshot re-pinned.

The comparison is feature-based, not byte-based: byte-equality between two
*different* code paths is neither achievable nor the point. ``figure_features``
extracts the load-bearing attributes (#98's regressions were all feature
*losses*: dropped ``:width:``, dropped image, leaked node text). The verdict
is: the marker path must not drop any feature the fallback produced.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parent.parent / 'scripts'
sys.path.insert(0, str(SCRIPTS))

import postprocess  # noqa: E402
from _config import load  # noqa: E402

CORPUS_DIR = Path(__file__).parent / 'marker_corpus'
PANDOC = shutil.which('pandoc')

# Preprocessors in preprocess.sh order. The figure-marker script is split out
# so the fallback path can run the chain *without* it.
_PRE_FIGURE_SCRIPTS = [
    '_apply_algorithm_markers.py',
    '_apply_algorithmic_markers.py',
    '_apply_listing_markers.py',
    '_apply_description_markers.py',
    '_apply_enumerate_markers.py',
    '_apply_table_markers.py',
]
_FIGURE_SCRIPT = '_apply_figure_markers.py'

_MINIMAL_CONFIG = {
    'source_dir': '.', 'output_dir': '.', 'tmp_dir': './tmp',
    'chapters': [{'stem': 'input', 'title': 'Differential'}],
}


def _run(tex_text: str, *, use_figure_markers: bool) -> str:
    """Run preprocess → pandoc → postprocess over ``tex_text``.

    ``use_figure_markers`` selects the path: True = marker path (default
    pipeline), False = fallback path (figure-marker preprocessor skipped, so
    pandoc emits the HTML ``<figure>`` that ``convert_html_figures`` handles).
    """
    scripts = list(_PRE_FIGURE_SCRIPTS)
    if use_figure_markers:
        scripts.append(_FIGURE_SCRIPT)

    with tempfile.TemporaryDirectory() as td:
        tex = Path(td) / 'input.tex'
        tex.write_text(tex_text, encoding='utf-8')
        for script in scripts:
            subprocess.run(
                [sys.executable, str(SCRIPTS / script), str(tex)],
                check=True, capture_output=True, text=True,
            )
        md = subprocess.run(
            [PANDOC, str(tex), '-f', 'latex', '-t', 'markdown', '--wrap=none'],
            check=True, capture_output=True, text=True,
        ).stdout

    postprocess.apply_config(dict(_MINIMAL_CONFIG), CORPUS_DIR)
    postprocess.TIKZ_FIGURE_MAP = {}
    postprocess.TIKZCD_INLINE_MAP = {}
    return postprocess.process_text(md, stem='input', title='Differential')


@dataclass(frozen=True)
class FigureFeatures:
    """Load-bearing figure attributes. Every #98 regression was a flip of one
    of these from present→absent at constant figure count."""
    n_figure_directives: int      # count, not boolean — subfigure expands to N
    n_widths: int                 # ``:width:`` lines
    n_named: int                  # ``:name:`` lines
    n_images: int                 # ``figures/<file>`` references
    has_nonempty_caption: bool
    # negative features — True is BAD (a leak the fallback didn't have)
    leaks_marker: bool            # raw ``<!--FIGURE`` / ``CELL_`` survived
    leaks_raw_latex: bool         # raw ``\begin{tikzpicture}`` / ``\includegraphics``
    leaks_cite_marker: bool       # ``[[CITEP`` / ``[[CITE`` survived


def figure_features(md: str) -> FigureFeatures:
    import re
    return FigureFeatures(
        n_figure_directives=len(re.findall(r'^```{figure}', md, re.MULTILINE)),
        n_widths=len(re.findall(r'^:width:', md, re.MULTILINE)),
        n_named=len(re.findall(r'^:name:', md, re.MULTILINE)),
        n_images=len(re.findall(r'figures/\S+', md)),
        has_nonempty_caption=bool(re.search(r'```{figure}[^\n]*\n(?:[^\n]*\n)*?\s*\S', md)),
        leaks_marker=('<!--FIGURE' in md) or ('CELL_' in md),
        leaks_raw_latex=('\\begin{tikzpicture}' in md) or ('\\includegraphics' in md),
        leaks_cite_marker=('[[CITEP' in md) or ('[[CITE:' in md),
    )


@dataclass(frozen=True)
class Verdict:
    case: str
    regressions: tuple[str, ...]   # features the marker path LOST vs fallback
    improvements: tuple[str, ...]  # features the marker path GAINED

    @property
    def ok(self) -> bool:
        return not self.regressions


def compare(case: str, old: FigureFeatures, new: FigureFeatures) -> Verdict:
    """Equal-or-better verdict: the marker (``new``) path must not drop any
    positive feature the fallback (``old``) produced, nor introduce a leak the
    fallback avoided. Gains are recorded as improvements (the Phase-4 win)."""
    regressions: list[str] = []
    improvements: list[str] = []

    def cmp_count(name: str, o: int, n: int) -> None:
        if n < o:
            regressions.append(f'{name}: {o} → {n}')
        elif n > o:
            improvements.append(f'{name}: {o} → {n}')

    cmp_count('figure directives', old.n_figure_directives, new.n_figure_directives)
    cmp_count('widths', old.n_widths, new.n_widths)
    cmp_count('names', old.n_named, new.n_named)
    cmp_count('images', old.n_images, new.n_images)
    if old.has_nonempty_caption and not new.has_nonempty_caption:
        regressions.append('caption: present → empty')

    # A leak present in new but not in old is a regression.
    for attr, label in (('leaks_marker', 'marker leak'),
                        ('leaks_raw_latex', 'raw-latex leak'),
                        ('leaks_cite_marker', 'cite-marker leak')):
        o, n = getattr(old, attr), getattr(new, attr)
        if n and not o:
            regressions.append(f'{label} introduced')
        elif o and not n:
            improvements.append(f'{label} fixed')
    return Verdict(case, tuple(regressions), tuple(improvements))


def differential_over_corpus(corpus: Path = CORPUS_DIR / 'figures') -> list[Verdict]:
    """Run both paths over every ``.tex`` block in ``corpus`` and return the
    per-case verdicts. Reusable by Phase 4 (import and assert ``v.ok``)."""
    verdicts = []
    for tex in sorted(corpus.glob('*.tex')):
        text = tex.read_text(encoding='utf-8')
        old = figure_features(_run(text, use_figure_markers=False))
        new = figure_features(_run(text, use_figure_markers=True))
        verdicts.append(compare(tex.stem, old, new))
    return verdicts


@pytest.mark.skipif(PANDOC is None, reason='pandoc not on PATH')
def test_marker_path_equal_or_better():
    """The marker path must be equal-or-better than the fallback on every
    corpus block. This is the gate that would have failed on each #98
    regression; in Phase 4 it gates the subfigure migration."""
    verdicts = differential_over_corpus()
    assert verdicts, 'differential corpus is empty'
    regressed = [v for v in verdicts if not v.ok]
    if regressed:
        report = '\n'.join(f'  {v.case}: lost {list(v.regressions)}' for v in regressed)
        pytest.fail(f'marker path regressed vs fallback on:\n{report}')


@pytest.mark.skipif(PANDOC is None, reason='pandoc not on PATH')
def test_differential_harness_runs_both_paths():
    """Smoke test: the harness actually exercises two distinct code paths.
    On the plain figure both paths should yield a figure directive."""
    text = (CORPUS_DIR / 'figures' / 'plain_width.tex').read_text(encoding='utf-8')
    old = figure_features(_run(text, use_figure_markers=False))
    new = figure_features(_run(text, use_figure_markers=True))
    assert new.n_figure_directives >= 1
    # marker path is the one that carries width through (the #98 #1 fix)
    assert new.n_widths >= old.n_widths
