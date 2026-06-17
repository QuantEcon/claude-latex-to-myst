"""`.tex`-rooted golden tier (Phase 1 — see ``notes/design/phase-1-validation-gate.md``).

Unlike ``tests/golden/`` — which starts from *pandoc output* and exercises
only ``process_text`` — each case here runs the **whole** pipeline against a
hand-authored ``input.tex``:

    preprocess (``_apply_rewrites`` + the marker scripts) → pandoc → postprocess

and diffs the result against a committed ``expected.md``.

This is the tier that would have caught the GH #98 figure regressions before
merge. All four (#98) are invisible to ``validate.py`` counts *and* to the
post-pandoc-only golden tier — a figure still counts as a figure — but a
``.tex`` → ``.md`` byte diff surfaces every one: the dropped ``:width:``, the
leading-space captions, the leaked TikZ node text, and the image dropped when
``\\includegraphics``'s path sits on the next line.

Layout::

    tests/golden_tex/<case>/
        input.tex          # hand-authored, one construct family
        config.yaml        # minimal per-case config
        expected.md        # committed golden
        tikz_overrides.py  # optional — cases needing a TIKZ_FIGURE_MAP entry

## Updating / adding fixtures

After an *intentional* behaviour change, re-capture and review the diff:

    UPDATE_GOLDEN=1 uv run pytest tests/test_golden_tex.py

The diff in ``expected.md`` IS the visible record of the change — commit it
alongside the transform. When adding a case, create ``input.tex`` +
``config.yaml`` (and ``tikz_overrides.py`` if needed), run with
``UPDATE_GOLDEN=1``, then **read** the generated ``expected.md`` before
committing — it becomes the contract.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parent.parent / 'scripts'
sys.path.insert(0, str(SCRIPTS))

import postprocess  # noqa: E402
from _config import load  # noqa: E402

GOLDEN_TEX_DIR = Path(__file__).parent / 'golden_tex'
PANDOC = shutil.which('pandoc')

# Marker preprocessors, in the exact order ``preprocess.sh`` runs them. Each
# takes a single ``.tex`` path and rewrites it in place; all are no-ops on
# sources that don't contain their construct, so running the full chain on a
# focused fixture is safe and keeps the harness faithful to the real pipeline.
_MARKER_SCRIPTS = [
    '_apply_pifont_glyphs.py',
    '_apply_prf_title_markers.py',
    '_apply_algorithm_markers.py',
    '_apply_algorithmic_markers.py',
    '_apply_listing_markers.py',
    '_apply_description_markers.py',
    '_apply_custom_label_enumerates.py',
    '_apply_enumerate_markers.py',
    '_apply_table_markers.py',
    '_apply_figure_markers.py',
]


def _cases() -> list[str]:
    if not GOLDEN_TEX_DIR.is_dir():
        return []
    return sorted(p.parent.name for p in GOLDEN_TEX_DIR.glob('*/input.tex'))


def _run_pipeline(case_dir: Path) -> str:
    """Run preprocess → pandoc → postprocess against ``case_dir/input.tex``.

    Mirrors ``convert.sh`` stage-for-stage: the preprocess scripts run as
    subprocesses (exactly as ``preprocess.sh`` invokes them), pandoc runs with
    the same flags, and ``process_text`` runs in-process after ``apply_config``
    (matching ``tests/test_golden.py``)."""
    config_path = case_dir / 'config.yaml'
    config = load(config_path)
    chapters = (config.get('chapters') or []) + (config.get('extra_files') or [])
    stem = chapters[0]['stem'] if chapters else 'input'
    title = chapters[0].get('title') if chapters else stem.replace('_', ' ').title()

    with tempfile.TemporaryDirectory() as td:
        tex = Path(td) / f'{stem}.tex'
        tex.write_text((case_dir / 'input.tex').read_text(encoding='utf-8'),
                       encoding='utf-8')

        # Stage 1: rewrites (built-in natbib + config strip/rewrites).
        subprocess.run(
            [sys.executable, str(SCRIPTS / '_apply_rewrites.py'),
             str(config_path), str(tex)],
            check=True, capture_output=True, text=True,
        )
        # Stage 1 (cont.): marker preprocessors, in preprocess.sh order.
        for script in _MARKER_SCRIPTS:
            subprocess.run(
                [sys.executable, str(SCRIPTS / script), str(tex)],
                check=True, capture_output=True, text=True,
            )
        # Stage 2: pandoc latex → markdown. Use the resolved PANDOC path the
        # skip guard checked, so the binary run matches the one tested for.
        md = subprocess.run(
            [PANDOC, str(tex), '-f', 'latex', '-t', 'markdown', '--wrap=none'],
            check=True, capture_output=True, text=True,
        ).stdout

    # Stage 3: postprocess (in-process, after applying the per-case config so
    # ENV_MAP / routing reflect the case). ``apply_config`` does NOT load the
    # TikZ map — ``process_file`` does that separately — so replicate that
    # step here, else cases that bail a tikzpicture to the TIKZ_FIGURE_MAP
    # path get an admonition instead of the mapped {figure}.
    postprocess.apply_config(config, case_dir)
    # Reset the TikZ maps to a clean slate per case (apply_config doesn't
    # touch them; only load_overrides binds them) so one case's map can't
    # bleed into the next when the suite runs all cases in one process.
    postprocess.TIKZ_FIGURE_MAP = {}
    postprocess.TIKZCD_INLINE_MAP = {}
    # ``project_overrides`` (Phase 5) is the preferred key; ``tikz_overrides``
    # is the retained alias — same loader.
    overrides_rel = config.get('project_overrides') or config.get('tikz_overrides')
    if overrides_rel:
        overrides_path = (case_dir / overrides_rel).resolve()
        if overrides_path.exists():
            postprocess.load_overrides(overrides_path)
    return postprocess.process_text(md, stem=stem, title=title)


def _diff(actual: str, expected: str, limit: int = 60) -> str:
    import difflib
    lines = list(difflib.unified_diff(
        expected.splitlines(keepends=True),
        actual.splitlines(keepends=True),
        fromfile='expected.md', tofile='actual', n=3,
    ))
    if len(lines) > limit:
        lines = lines[:limit] + [f'... ({len(lines) - limit} more lines)\n']
    return ''.join(lines) or '(no textual diff)'


@pytest.mark.skipif(PANDOC is None, reason='pandoc not on PATH')
@pytest.mark.parametrize('case', _cases())
def test_golden_tex(case: str):
    case_dir = GOLDEN_TEX_DIR / case
    actual = _run_pipeline(case_dir)
    out_path = case_dir / 'expected.md'

    if os.environ.get('UPDATE_GOLDEN') == '1':
        out_path.write_text(actual, encoding='utf-8')
        pytest.skip(f'updated {case}/expected.md')

    if not out_path.exists():
        pytest.fail(
            f'{case}/expected.md missing — run UPDATE_GOLDEN=1 to generate, '
            'then read it before committing.'
        )
    expected = out_path.read_text(encoding='utf-8')
    if actual != expected:
        pytest.fail(f'golden_tex mismatch for {case!r}:\n{_diff(actual, expected)}')


def test_golden_tex_seeded():
    """Guard: the seeded reproducers must stay in the corpus.

    Two groups: the four #98 figure-marker regressions (the cases that
    motivated this tier), and the Phase-1 seeding from the pandoc-quirk
    lesson catalogue (each maps to a codified lesson — see
    ``LESSON_COVERAGE.md``). A lesson with no reproducer here is one that
    can silently regress, so the corpus is not allowed to shrink below this
    set without a deliberate edit to this guard."""
    cases = set(_cases())
    required = {
        # #98 figure-marker regression reproducers (the motivating cases)
        'figure_width_option',
        'figure_label_in_caption',
        'figure_raw_tikzpicture_with_override_bails',
        'figure_includegraphics_path_on_next_line',
        'subfigure_includegraphics',      # #94 (Phase 4)
        'subfigure_outer_and_panel_labels',  # Copilot review: outer label kept
        'tikz_figure_caption_math',        # Phase 6 tikz caption-math preservation
        'post_convert_fence_aware',        # Phase 5 book-side POST_CONVERT
        # Phase-1 seeding from the lesson catalogue (lesson id in comment)
        'table_float_hline',              # 019 / 025
        'cite_textual_colon_key',         # 031 / 035
        'cite_natbib_variants',           # 020
        'cref_comma_split',               # 007
        'doubled_noun_ref',               # 011
        'doubled_section_noun_ref',       # 016 / #150
        'math_text_dollar',               # 003
        'math_percent_comment',           # 006
        'math_thin_space_superscript',    # 042
        'align_per_row_labels',           # 032
        'description_item_labels',        # 022
        'lstlisting_code_block',          # 034
        'unnumbered_section_label',       # 017
        'figure_caption_citation',        # 043
        'algorithm2e_block',              # 014 / 023
        'enumerate_exercise',             # 039
        'multline_gather_labels',         # 037
    }
    missing = required - cases
    assert not missing, f'golden_tex missing seeded reproducer cases: {sorted(missing)}'
