"""Lock the canonical call order in ``process_file``.

Codifies [lesson 008](../lessons/008-pipeline-ordering.md): "post-processing
transform order is critical and fragile." The order is load-bearing —
reordering casually has produced several historical bugs (e.g. issue #27).

The unit-test suite calls each transform in isolation and never notices
ordering drift. This file is the one place an accidental reorder is
detected at CI time.

When intentionally reordering ``process_file``, update
``EXPECTED_PIPELINE_ORDER`` below to match the new sequence. That
edit is the explicit, reviewable record of the change.
"""

from __future__ import annotations

import inspect
import re

import postprocess


# Canonical order of transform calls inside ``process_file``. Each entry
# is the function name as it appears on the ``text = X(text)`` line.
# Non-transform statements (variable assignments, ``read_text``,
# ``write_text``, ``print``) are skipped by the extractor below.
#
# Update this list when ``process_file`` intentionally changes. CI fails
# loudly otherwise — the goal is to make reorders explicit.
EXPECTED_PIPELINE_ORDER: list[str] = [
    'strip_pandoc_html_separators',
    'fix_text_dollar',
    'convert_epigraphs',
    'convert_pandoc_attr_code_blocks',
    'resolve_table_markers',
    'resolve_figure_markers',
    'convert_simple_tables',
    # convert_equations precedes the env/exercise emitters so their
    # outer_fence() sizing sees the ```{math} fences starred displays now
    # emit (#113); converted after, an inner {math} closer would terminate
    # a theorem/exercise directive early (the issue-#79 ordering class).
    'convert_equations',
    'convert_environment_divs',
    'convert_description_lists',
    'resolve_exercise_markers',
    'decode_natbib_markers',
    'convert_cross_references',
    'strip_doubled_noun_refs',
    'strip_doubled_section_symbol',
    'convert_figures',
    'convert_html_figures',
    'resolve_tikz_figures',
    'convert_section_labels',
    'hoist_consecutive_heading_labels',
    'convert_citations',
    'convert_standalone_labels',
    'resolve_listings',
    'resolve_algorithms',
    'resolve_algorithmics',
    'fix_spacing_superscript',
    'join_split_inline_math',
    'ensure_blank_after_display_math',
    'convert_pandoc_spans',
    'cleanup_typography',
    'strip_blank_lines_in_math',
    'strip_footnote_refs',
    'compress_directive_whitespace',
    'add_frontmatter',
    'apply_postprocess_rewrites',
]


# A ``text = NAME(text...)`` line, where NAME is a bare identifier (not
# attribute access, not a regex sub). Captures NAME.
_CALL_RE = re.compile(
    r'^\s*text\s*=\s*([A-Za-z_][A-Za-z0-9_]*)\s*\(',
    re.MULTILINE,
)


def _extract_call_sequence(func) -> list[str]:
    """Return the bare-name function calls assigned to ``text`` in
    source order. Ignores ``text = re.sub(...)`` and similar attribute
    calls — only direct calls to top-level transforms register."""
    src = inspect.getsource(func)
    return _CALL_RE.findall(src)


def test_process_text_call_order_matches_expected():
    """Reorder guard: every reorder must explicitly update
    ``EXPECTED_PIPELINE_ORDER``. Lesson 008.

    Inspects ``process_text`` (the pure in-memory pipeline extracted
    in P0c). ``process_file`` is a thin I/O wrapper that delegates
    to ``process_text`` for the actual transform sequence."""
    actual = _extract_call_sequence(postprocess.process_text)
    assert actual == EXPECTED_PIPELINE_ORDER, (
        "Pipeline order drift detected.\n"
        f"  expected: {EXPECTED_PIPELINE_ORDER}\n"
        f"  actual:   {actual}\n"
        "If this reorder is intentional, update EXPECTED_PIPELINE_ORDER "
        "in tests/test_pipeline_order.py."
    )


def test_every_expected_function_exists_on_module():
    """Sanity guard: every name in ``EXPECTED_PIPELINE_ORDER`` is
    callable on ``postprocess``. Catches typos and rename drift."""
    for name in EXPECTED_PIPELINE_ORDER:
        fn = getattr(postprocess, name, None)
        assert callable(fn), (
            f"EXPECTED_PIPELINE_ORDER references {name!r} but "
            f"postprocess.{name} is not callable. Did the function "
            "get renamed?"
        )
