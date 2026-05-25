"""Regression tests for ``postprocess.py`` invoked as a script.

When ``postprocess.py`` runs as ``python3 postprocess.py …`` it loads
under the module name ``__main__``. Every transform in
``scripts/transforms/`` late-imports ``postprocess`` to read module-level
state mutated by ``apply_config`` / ``load_overrides``. Without the
``sys.modules['postprocess'] = sys.modules[__name__]`` alias at the top
of ``postprocess.py``, that late-import returns a *second* copy of the
module with the defaults frozen — and every config-extension or
override silently no-ops.

The other test files in this directory ``import postprocess`` directly,
so the module loads under the name ``postprocess`` from the start and
the bug is invisible to them. These tests shell out via ``subprocess``
to reproduce the real ``convert.sh`` invocation path. See GH issue #42
and lesson 038.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


_REPO_ROOT = Path(__file__).resolve().parent.parent
_POSTPROCESS = _REPO_ROOT / "scripts" / "postprocess.py"


def _run_postprocess(config: Path, *inputs: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(_POSTPROCESS), "--config", str(config), *map(str, inputs)],
        capture_output=True,
        text=True,
    )


def test_tikz_overrides_apply_when_run_as_main(tmp_path):
    """``TIKZ_FIGURE_MAP`` loaded by ``main()`` must reach
    ``resolve_tikz_figures``, even though ``main()`` mutates state in
    the ``__main__`` namespace and the transform late-imports under
    ``postprocess``. Regression test for #42.
    """
    overrides = tmp_path / "tikz_overrides.py"
    overrides.write_text(
        "TIKZ_FIGURE_MAP = {'fig-test': ('figures/x.svg', None)}\n"
        "TIKZCD_INLINE_MAP = {}\n",
        encoding="utf-8",
    )
    config = tmp_path / "config.yaml"
    config.write_text(
        "source_dir: .\n"
        f"tikz_overrides: {overrides.name}\n",
        encoding="utf-8",
    )
    md = tmp_path / "t.md"
    md.write_text(
        "```{admonition} Figure (TikZ — needs manual conversion)\n"
        ":name: fig-test\n"
        "\n"
        "Caption.\n"
        "```\n",
        encoding="utf-8",
    )

    result = _run_postprocess(config, md)

    assert result.returncode == 0, (
        f"postprocess.py exited {result.returncode}\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )
    out = md.read_text(encoding="utf-8")
    assert "```{figure} figures/x.svg" in out, (
        f"TikZ placeholder did not resolve; output was:\n{out}"
    )
    assert "TikZ — needs manual conversion" not in out, (
        f"placeholder survived into output:\n{out}"
    )


def test_extra_environments_apply_when_run_as_main(tmp_path):
    """``apply_config`` extensions to ``ENV_MAP`` must also reach the
    transform-side late-import under ``__main__``. Same bug class as the
    TikZ regression — different state dict, same failure mode if the
    module aliasing regresses.
    """
    config = tmp_path / "config.yaml"
    config.write_text(
        "source_dir: .\n"
        "extra_environments:\n"
        "  customthm: prf:theorem\n",
        encoding="utf-8",
    )
    md = tmp_path / "u.md"
    md.write_text(
        "::: customthm\n"
        "Body of the custom theorem.\n"
        ":::\n",
        encoding="utf-8",
    )

    result = _run_postprocess(config, md)

    assert result.returncode == 0, (
        f"postprocess.py exited {result.returncode}\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )
    out = md.read_text(encoding="utf-8")
    assert "```{prf:theorem}" in out, (
        f"custom env did not map via extra_environments; output:\n{out}"
    )
