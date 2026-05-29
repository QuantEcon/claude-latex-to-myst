"""Per-family transform modules.

The pipeline orchestrator is ``postprocess.py``. The transform functions
themselves live in themed submodules of this package. ``postprocess.py``
re-exports every public symbol so the test surface and external import
path (``import postprocess; postprocess.convert_X(...)``) remain stable.

## State threading (``ConversionContext`` — Phase 3)

Run state lives on a :class:`conversion_context.ConversionContext`, built
once by ``ConversionContext.from_config`` and threaded as an argument — no
more mutated module globals on ``postprocess``. The context carries:

  - ``env_map`` / ``env_skip`` — environment-div mapping
  - ``chapter_titles`` / ``chapter_styles`` — per-file frontmatter
  - ``tikz_figure_map`` / ``tikzcd_inline_map`` — TikZ overrides
  - ``listing_source_base`` — minted source-code base path
  - ``cross_ref_routing`` / ``doubled_noun_refs`` — per-book extras
  - ``postprocess_rewrites`` — book-specific post-rewrites
  - ``frontmatter_style`` / ``whitespace_style`` — config flags
  - ``counters`` — per-file exercise numbering, reset by ``process_text``

A transform that needs state takes ``ctx`` and reads from it; transforms
that are already pure (most of ``math`` / ``cite``) stay pure. When called
without an explicit ``ctx`` (the unit-test path), a transform falls back to
``conversion_context.current_context()`` — the context ``apply_config``
registered. ``process_text`` threads ``ctx`` explicitly, which is what
makes the pipeline reentrant (two books, two contexts, one process).

Example::

    # transforms/envs.py
    from conversion_context import current_context

    def convert_environment_divs(text: str, ctx=None) -> str:
        ctx = ctx if ctx is not None else current_context()
        env_map = ctx.env_map
        env_skip = ctx.env_skip
        # ... use env_map / env_skip

For backward compatibility the old ``postprocess.ENV_MAP`` (etc.) names
still work — they are transparent views on the current context, provided by
the module-proxy at the bottom of ``postprocess.py`` (a test-compat shim;
production code threads ``ctx``). Lesson 038's ``sys.modules`` alias is gone
because the state no longer lives on ``postprocess``.

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
