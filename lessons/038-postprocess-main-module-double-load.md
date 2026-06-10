---
id: 038
title: "Late-import of ``postprocess`` from transform modules loads a second copy when ``postprocess.py`` runs as ``__main__``"
category: tooling
tags: [python, modules, late-import, regression, state, p3a-refactor]
source_project: external book (Deep_Learning_for_Solving_And_Estimating_Dynamic_Economic_Models)
status: superseded
codified_in: scripts/postprocess.py (top-of-file ``sys.modules`` aliasing)
superseded_by: "Phase 3 ConversionContext (notes/design/phase-3-conversion-context.md); scripts/conversion_context.py"
severity: high
date: 2026-05-25
---

> **SUPERSEDED (Phase 3, architecture-evolution).** The root cause — run
> state living as *mutated module globals on ``postprocess``* — has been
> removed. State now lives on a ``ConversionContext`` threaded as an
> argument (``scripts/conversion_context.py``), so there is no per-module
> singleton for a second module-load to freeze. The ``sys.modules`` alias
> this lesson documents is **gone**; transforms no longer ``import
> postprocess`` (they read ``ctx`` / ``conversion_context.current_context()``).
> The fix below is kept for provenance — it was the correct stopgap while
> state was global. The reentrancy proof is
> ``tests/test_conversion_context.py``.

## Symptom

After the P3a refactor split ``postprocess.py`` into themed transform
modules (``scripts/transforms/*.py``), every consumer book that uses
``tikz_overrides.py`` to map TikZ placeholder labels to figure paths
silently stopped resolving figures. The pipeline ran cleanly with no
errors — but 0 of N admonition placeholders were converted to
``{figure}`` directives. Diagnostic prints showed
``TIKZ_FIGURE_MAP`` populated with the right entries in
``load_overrides`` but **empty** when read inside
``resolve_tikz_figures``.

Same shape applied to every transform that read module-level state
populated by ``apply_config`` / ``load_overrides`` — including
``ENV_MAP`` extensions (``extra_environments:``), ``CHAPTER_TITLES``,
``_EXTRA_CROSS_REF_ROUTING``, ``_EXTRA_DOUBLED_NOUN_REFS``,
``POSTPROCESS_REWRITES``, and the per-stem frontmatter / whitespace
flags. TikZ was the most visible because the failure produced a
rendered placeholder; the others failed silently (custom env not
mapped, custom cross-ref prefix not routed, …) and would have wasted
hours to track down individually.

## Cause

Classic Python module double-load.

``scripts/convert.sh`` invokes the post-processor as
``python3 scripts/postprocess.py --config …``. Python loads
``postprocess.py`` under the module name ``__main__``. ``main()``
calls ``apply_config`` and ``load_overrides`` which mutate
``TIKZ_FIGURE_MAP`` / ``ENV_MAP`` / etc. **in the** ``__main__``
**namespace**.

Transforms in ``scripts/transforms/`` read that state via late-import:

```python
def resolve_tikz_figures(text: str, stem: str) -> str:
    import postprocess
    tikz_figure_map = postprocess.TIKZ_FIGURE_MAP
    ...
```

When this runs under script invocation, Python does **not** notice
that the currently-executing module *is* ``postprocess.py`` — because
its registered name is ``__main__``, not ``postprocess``. ``import
postprocess`` therefore loads ``postprocess.py`` a *second time*,
under the name ``postprocess``. That second module instance has
``TIKZ_FIGURE_MAP = {}`` at module-init and never sees the
mutations done in ``__main__``.

The pre-P3a monolith hid the bug because every transform read state
directly off its own enclosing module — no late-import, no second
copy. The refactor moved transforms into sibling modules without
considering that the import sentinel they would land on (``import
postprocess``) is *different from* the module they were copied out
of (``__main__``) when run as a script.

## Fix

Three lines at the top of ``scripts/postprocess.py``, immediately
after imports:

```python
if __name__ == '__main__':
    sys.modules['postprocess'] = sys.modules[__name__]
```

This registers the ``__main__`` module instance under the additional
name ``postprocess``. Every subsequent ``import postprocess`` (from
any transform) resolves to the same module instance — the one whose
state ``apply_config`` / ``load_overrides`` mutated.

When ``postprocess`` is imported normally (e.g. ``import postprocess``
from a test file, or from another tool), ``sys.modules['postprocess']``
is already set and the guard is a no-op.

Three options were considered (in GH issue #42):

- **(A)** ``__main__`` fallback inside every late-import site. Works
  but has to be repeated across 9 sites in ``scripts/transforms/``
  and would have to be remembered on every new transform.
- **(B)** Top-of-file ``sys.modules`` alias — chosen. One location,
  fixes all current and future late-import sites at once.
- **(C)** Move all mutable state into a dedicated ``transforms/_state.py``
  module. Cleaner long-term but conflicts with the
  "mutable state on ``postprocess.py`` as single source of truth"
  decision in CLAUDE.md, and is a much larger refactor.

## How to detect

The existing test suite imports ``postprocess`` directly
(``import postprocess``), so the module loads under the name
``postprocess`` from the start and the bug is **invisible** to every
test that doesn't shell out. The regression test in
``tests/test_main_invocation.py`` runs ``postprocess.py`` via
``subprocess`` so it loads as ``__main__`` — that's the only way to
exercise the double-load path.

When auditing a new transform that needs module-level state, the
checklist is:

1. Does it ``import postprocess`` inside the function body? (Yes for
   the established late-import pattern.)
2. Does it read state mutated by ``apply_config`` or
   ``load_overrides``? (TIKZ_FIGURE_MAP, ENV_MAP, CHAPTER_TITLES,
   any ``_EXTRA_*`` list, ``POSTPROCESS_REWRITES``, frontmatter /
   whitespace flags.)

If both are yes, the ``sys.modules`` alias at the top of
``postprocess.py`` is what keeps it working. Do not remove that
guard. The lesson 038 regression test will catch removal.

## Generalizable rule

**Splitting a script into helper modules changes the import identity
of "the script" from the helpers' perspective.** When the original
single-file script is invoked as ``__main__``, helpers that
late-import it by name (``import script_name``) get a second copy of
the module, with module-level mutations from the first copy
invisible. The lightweight fix is the top-of-file ``sys.modules``
alias inside ``if __name__ == '__main__':``. The structural fix is
to move the shared state out of the script into a leaf module both
the script and the helpers import — but that's a refactor, not a
rescue.

In Python, ``__name__`` is the cheapest identity check there is,
and it's also the one that most often disagrees with the import name
of the file. Any pattern that mixes "I'm the script" with "I'm a
library module" needs the alias to bridge the two.
