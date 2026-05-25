"""Per-family transform modules.

The pipeline orchestrator is ``postprocess.py``. The transform functions
themselves live in themed submodules of this package. ``postprocess.py``
re-exports every public symbol so the test surface and external import
path (``import postprocess; postprocess.convert_X(...)``) remain stable.

## State-coupling pattern

Mutable module-level state lives on ``postprocess`` (populated by
``apply_config`` / ``load_overrides``):

  - ``ENV_MAP`` / ``ENV_SKIP`` — environment-div mapping
  - ``CHAPTER_TITLES`` / ``CHAPTER_STYLES`` — per-file frontmatter
  - ``TIKZ_FIGURE_MAP`` / ``TIKZCD_INLINE_MAP`` — TikZ overrides
  - ``_LISTING_SOURCE_BASE`` — minted source-code base path
  - ``_EXTRA_CROSS_REF_ROUTING`` / ``_EXTRA_DOUBLED_NOUN_REFS`` —
    per-book config-extension lists
  - ``POSTPROCESS_REWRITES`` — book-specific post-rewrites
  - ``_FRONTMATTER_STYLE`` / ``_WHITESPACE_STYLE`` — config flags
  - ``_last_exercise_label`` / ``_exercise_counter`` /
    ``_chapter_prefix`` — per-file state reset by ``process_text``

Transform modules that need this state late-import ``postprocess``
*inside* the function (not at module load) to avoid the circular
import that would otherwise happen at package load. Modules that
need it mark this in their docstring under a "State coupling"
header.

Example::

    # transforms/envs.py
    def convert_environment_divs(text: str) -> str:
        import postprocess as pp
        env_map = pp.ENV_MAP
        env_skip = pp.ENV_SKIP
        # ... use env_map / env_skip

The single-source-of-truth on ``postprocess`` means ``apply_config``
mutates state in one place, and all transform modules see the
updates at their next call.

## Adding a new transform module

1. Create ``scripts/transforms/<theme>.py`` with `from __future__ import
   annotations` and any needed local imports (typically ``re`` and
   ``from ._helpers import convert_label_colons``).
2. Add a re-export block to ``scripts/postprocess.py``'s import section.
3. Add the call to ``process_text`` at the right pipeline position.
4. Update ``tests/test_pipeline_order.py::EXPECTED_PIPELINE_ORDER``.
5. Add tests; if the transform belongs to an existing family, extend the
   appropriate ``tests/test_*_shapes.py`` parametrize matrix.
"""
