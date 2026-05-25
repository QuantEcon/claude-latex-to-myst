"""End-to-end golden-file tests for the full ``process_text`` pipeline.

Each fixture pair ``<name>.in.md`` / ``<name>.out.md`` in ``tests/golden/``
captures a pandoc-output snippet and the current expected MyST output.
The full transform pipeline runs on the input; the output is compared
byte-for-byte against the expected.

These tests are the safety net for cross-cutting refactors (P0c in
QUALITY-REVIEW.md). The 155 unit tests call individual transforms; this
file is the one place an unintended interaction regression is caught.

## When to update fixtures

When a transform's behaviour CHANGES INTENTIONALLY (a fix, a feature),
the affected golden(s) will fail. Re-capture with:

    UPDATE_GOLDEN=1 uv run pytest tests/test_golden.py

Review the resulting diff in ``tests/golden/*.out.md`` — that diff IS
the visible record of the behaviour change. Commit it alongside the
transform change.

When ADDING a new fixture, create ``<name>.in.md`` only, then run with
``UPDATE_GOLDEN=1`` to generate the matching ``.out.md``. Manually
review the output before committing — it becomes the contract.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

import postprocess


GOLDEN_DIR = Path(__file__).parent / 'golden'


def _golden_names() -> list[str]:
    """Discover all fixtures (anything with a matching ``.in.md``)."""
    if not GOLDEN_DIR.is_dir():
        return []
    return sorted(p.stem.removesuffix('.in')
                  for p in GOLDEN_DIR.glob('*.in.md'))


def _diff(actual: str, expected: str, limit: int = 40) -> str:
    """Return a unified-ish diff suitable for pytest assertion output."""
    import difflib
    lines = list(difflib.unified_diff(
        expected.splitlines(keepends=True),
        actual.splitlines(keepends=True),
        fromfile='expected', tofile='actual',
        n=3,
    ))
    if len(lines) > limit:
        lines = lines[:limit] + [f'... ({len(lines) - limit} more diff lines truncated)\n']
    return ''.join(lines) or '(no textual diff produced)'


@pytest.mark.parametrize("name", _golden_names())
def test_golden(name: str):
    """Run the full pipeline against the fixture; assert byte-equal output."""
    in_path = GOLDEN_DIR / f'{name}.in.md'
    out_path = GOLDEN_DIR / f'{name}.out.md'

    input_text = in_path.read_text(encoding='utf-8')
    # Title defaults to a humanised version of the fixture name so the
    # frontmatter pass has a non-empty value to render.
    title = name.replace('_', ' ').title()
    actual = postprocess.process_text(input_text, stem=name, title=title)

    if os.environ.get('UPDATE_GOLDEN') == '1':
        out_path.write_text(actual, encoding='utf-8')
        pytest.skip(f'updated {out_path.name}')

    if not out_path.exists():
        pytest.fail(
            f'{out_path.name} missing — run UPDATE_GOLDEN=1 to generate, '
            'then manually inspect before committing.'
        )

    expected = out_path.read_text(encoding='utf-8')
    if actual != expected:
        pytest.fail(
            f'golden mismatch for {name!r}:\n{_diff(actual, expected)}\n'
            f'If this change is intentional, re-capture with '
            f'UPDATE_GOLDEN=1 uv run pytest tests/test_golden.py'
        )


def test_golden_dir_is_populated():
    """Sanity guard: catch an accidentally-empty golden dir (e.g. someone
    nukes ``tests/golden/`` and the rest of the tests skip silently)."""
    names = _golden_names()
    assert len(names) >= 8, (
        f'tests/golden/ has only {len(names)} fixture(s); the safety net '
        'should cover all major transform families. See QUALITY-REVIEW.md '
        '§P0c for the canonical fixture list.'
    )
