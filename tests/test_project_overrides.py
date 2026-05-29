"""Phase 5 — book-side ``project_overrides.py`` (see
``notes/design/phase-5-book-overrides.md``).

The override file is a **closed** surface read by ``load_overrides`` into the
``ConversionContext``: ``TIKZ_FIGURE_MAP`` / ``TIKZCD_INLINE_MAP`` (already
supported), ``EXTRA_REWRITES`` (appended to ``ctx.postprocess_rewrites``), and
one optional ``POST_CONVERT(text, stem, ctx)`` hook (held on ``ctx``, run once
near the end of ``process_text``). It *contributes* to the context — it never
mutates module globals (the lesson-038 trap Phase 3 removed).
"""

from __future__ import annotations

import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / 'scripts'
sys.path.insert(0, str(SCRIPTS))

import postprocess  # noqa: E402
from conversion_context import ConversionContext  # noqa: E402


def _write(tmp_path: Path, body: str) -> Path:
    p = tmp_path / 'project_overrides.py'
    p.write_text(body, encoding='utf-8')
    return p


def test_extra_rewrites_flow_through_context(tmp_path):
    """EXTRA_REWRITES are compiled and appended to ctx.postprocess_rewrites,
    then applied by the normal postprocess-rewrite pass."""
    ctx = ConversionContext.from_config({'source_dir': '.'})
    before = len(ctx.postprocess_rewrites)
    ov = _write(tmp_path, "EXTRA_REWRITES = [(r'FOObar', 'BAZ')]\n")
    postprocess.load_overrides(ov, ctx)
    assert len(ctx.postprocess_rewrites) == before + 1
    out = postprocess.process_text('a FOObar b\n', stem='ch_x', title='X', ctx=ctx)
    assert 'BAZ' in out and 'FOObar' not in out


def test_extra_rewrites_honour_stems(tmp_path):
    """A 3-tuple EXTRA_REWRITES rule scopes to specific stems."""
    ctx = ConversionContext.from_config({'source_dir': '.'})
    ov = _write(tmp_path, "EXTRA_REWRITES = [(r'WIDGET', 'gadget', ['ch_only'])]\n")
    postprocess.load_overrides(ov, ctx)
    on = postprocess.process_text('a WIDGET b\n', stem='ch_only', title='Y', ctx=ctx)
    off = postprocess.process_text('a WIDGET b\n', stem='ch_other', title='Z', ctx=ctx)
    assert 'gadget' in on
    assert 'WIDGET' in off and 'gadget' not in off


def test_post_convert_runs_at_documented_point(tmp_path):
    """POST_CONVERT is held on the context and invoked on the final MyST."""
    ctx = ConversionContext.from_config({'source_dir': '.'})
    ov = _write(tmp_path,
                "def POST_CONVERT(text, stem, ctx):\n"
                "    return text + f'\\n<!-- hooked:{stem} -->\\n'\n")
    postprocess.load_overrides(ov, ctx)
    assert ctx.post_convert is not None
    out = postprocess.process_text('Hello.\n', stem='ch_h', title='H', ctx=ctx)
    assert '<!-- hooked:ch_h -->' in out


def test_post_convert_can_be_fence_aware(tmp_path):
    """A fence-aware POST_CONVERT rewrites prose but leaves a fenced code
    block untouched — the conservatism the surface requires."""
    ctx = ConversionContext.from_config({'source_dir': '.'})
    ov = _write(tmp_path,
                "def POST_CONVERT(text, stem, ctx):\n"
                "    out, fence = [], False\n"
                "    for line in text.split('\\n'):\n"
                "        if line.lstrip().startswith('```'):\n"
                "            fence = not fence; out.append(line); continue\n"
                "        out.append(line if fence else line.replace('TOK', 'OK'))\n"
                "    return '\\n'.join(out)\n")
    postprocess.load_overrides(ov, ctx)
    src = 'prose TOK here\n\n```python\ncode TOK here\n```\n'
    out = postprocess.process_text(src, stem='ch_f', title='F', ctx=ctx)
    assert 'prose OK here' in out          # prose rewritten
    assert 'code TOK here' in out          # code block untouched


def test_extra_rewrites_string_stems_rejected(tmp_path):
    """Footgun guard (Copilot review): a bare-string ``stems`` (instead of a
    list) would become ``frozenset('ch_only')`` = {'c','h',…} and silently
    never match. It must raise instead."""
    import pytest
    ctx = ConversionContext.from_config({'source_dir': '.'})
    ov = _write(tmp_path, "EXTRA_REWRITES = [(r'X', 'Y', 'ch_only')]\n")
    with pytest.raises(SystemExit):
        postprocess.load_overrides(ov, ctx)


def test_post_convert_must_be_callable(tmp_path):
    import pytest
    ctx = ConversionContext.from_config({'source_dir': '.'})
    ov = _write(tmp_path, "POST_CONVERT = 'not callable'\n")
    with pytest.raises(SystemExit):
        postprocess.load_overrides(ov, ctx)


def test_tikz_overrides_filename_still_loads(tmp_path):
    """The old filename ``tikz_overrides.py`` (just the two maps) still loads
    under the same loader — the alias retained for one release."""
    ctx = ConversionContext.from_config({'source_dir': '.'})
    p = tmp_path / 'tikz_overrides.py'
    p.write_text("TIKZ_FIGURE_MAP = {'f-x': ('figures/x.svg', None)}\n", encoding='utf-8')
    postprocess.load_overrides(p, ctx)
    assert ctx.tikz_figure_map == {'f-x': ('figures/x.svg', None)}
    assert ctx.post_convert is None  # absent attributes ignored (closed surface)


def test_loader_ignores_unknown_attributes(tmp_path):
    """The closed surface reads only the documented attributes; anything else
    in the file is ignored (no registration API)."""
    ctx = ConversionContext.from_config({'source_dir': '.'})
    ov = _write(tmp_path,
                "TIKZ_FIGURE_MAP = {}\n"
                "SOMETHING_ELSE = 42\n"
                "def helper(): return 1\n")
    postprocess.load_overrides(ov, ctx)  # must not raise
    assert ctx.post_convert is None
