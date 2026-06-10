# Phase 3 — `ConversionContext` (state threading)

**Status:** LANDED (architecture-evolution branch, commit 3/5) · **Effort:** ~3–5 days, incremental · **Risk:** medium · **Depends on:** Phase 1 gate (non-negotiable)

> **Landed.** `scripts/conversion_context.py` holds `ConversionContext`
> (+ `FileCounters`, `from_config`, `default`, and a `current_context()`
> registry). `postprocess.apply_config` builds the ctx and registers it;
> `process_text(…, ctx=…)` threads it; the six stateful transform families
> (typography, refs, code, frontmatter, envs, figures/figures_from_latex)
> read `ctx` (math/cite stayed pure). All module globals and the
> `sys.modules` alias are gone; `grep import postprocess scripts/transforms/`
> is clean. A backward-compat **module proxy** at the bottom of
> `postprocess.py` keeps the legacy `postprocess.ENV_MAP` (etc.) names
> working as views on the current context, so the ~600 unit tests were
> unchanged. Reentrancy proof: `tests/test_conversion_context.py` (two books
> one process, no bleed; per-file counters reset). Lesson 038 marked
> superseded. Snapshot byte-identical ×3 throughout.

## Problem — the deepest finding of the review

The whole post-pandoc pipeline funnels through **module-level mutable
globals** on [`postprocess.py`](../../scripts/postprocess.py):

- Config-derived: `ENV_MAP`, `ENV_SKIP`, `CHAPTER_TITLES`,
  `CHAPTER_STYLES`, `TIKZ_FIGURE_MAP`, `TIKZCD_INLINE_MAP`,
  `_EXTRA_CROSS_REF_ROUTING`, `_EXTRA_DOUBLED_NOUN_REFS`,
  `_LISTING_SOURCE_BASE`, `POSTPROCESS_REWRITES`, `_FRONTMATTER_STYLE`,
  `_WHITESPACE_STYLE` — all mutated by `apply_config`
  ([381–544](../../scripts/postprocess.py#L381-L544)).
- Per-file: `_last_exercise_label`, `_exercise_counter`,
  `_chapter_prefix` — reset at the top of `process_text`
  ([563–567](../../scripts/postprocess.py#L563-L567)).

Seven transform modules read these by late-`import postprocess` inside
their functions ([envs](../../scripts/transforms/envs.py#L36),
[refs](../../scripts/transforms/refs.py#L143),
[figures](../../scripts/transforms/figures.py#L286),
[figures_from_latex](../../scripts/transforms/figures_from_latex.py#L266),
[code](../../scripts/transforms/code.py#L162),
[frontmatter](../../scripts/transforms/frontmatter.py#L99),
[typography](../../scripts/transforms/typography.py#L93)).

### Why this blocks "general conversion"

1. **Non-reentrant.** Two configs cannot coexist in one process. A
   library/API entry point, or a CI loop converting several fixture books
   in-process, must fork or manually reset globals between runs.
2. **It is the root of a 🔴 lesson.** Lesson
   [038](../../lessons/038-postprocess-main-module-double-load.md) — the
   `__main__`-vs-`postprocess` double-load that silently froze every
   config-derived map — exists *only because* state is a mutated module
   singleton. The `sys.modules` alias at
   [postprocess.py:39–40](../../scripts/postprocess.py#L39-L40) is a
   workaround for a problem that disappears if state is an argument.
3. **Non-local reasoning + test friction.** "Where did `ENV_MAP` get this
   value?" is never answerable locally; tests must reset globals between
   cases.

## Design

Introduce a `ConversionContext` dataclass that holds what the globals
hold, and thread it as the first argument to every transform that needs
state. Transforms that are already pure (most math/typography) stay pure.

```python
@dataclass
class ConversionContext:
    # config-derived (built once by from_config)
    env_map: dict
    env_skip: frozenset
    chapter_titles: dict
    chapter_styles: dict
    tikz_figure_map: dict
    tikzcd_inline_map: dict
    cross_ref_routing: list
    doubled_noun_refs: list
    listing_source_base: Path | None
    postprocess_rewrites: list
    frontmatter_style: str
    whitespace_style: str
    # per-file mutable counters live in a nested, explicitly-reset sub-object
    counters: FileCounters

    @classmethod
    def from_config(cls, config: dict, base_dir: Path | None) -> "ConversionContext": ...
```

`process_text(text, stem, ctx, ...)` builds/receives a `ctx`; each
transform signature becomes `convert_X(text, ctx)`. `apply_config`
becomes `ConversionContext.from_config` (a constructor, no mutation).

### Migration strategy — incremental, one family at a time

This is the part that keeps the refactor safe and reviewable:

1. **Land Phase 1 first.** The byte-diff golden gate is what proves each
   step is behavior-preserving. Do not start Phase 3 without it.
2. Introduce `ConversionContext` and `from_config` alongside the existing
   globals (both populated). No behavior change yet.
3. Migrate **one transform family per PR**: change its signature to take
   `ctx`, update `process_text`'s call site and the re-export, switch its
   reads from `import postprocess` to `ctx`. Golden gate must stay green.
   Order by blast radius — start with the smallest reader (typography),
   end with the largest (figures).
4. When the last reader is migrated, delete the module globals, delete the
   `sys.modules` alias, and **mark lesson 038 superseded** (don't delete
   it — note that the root cause was removed).

### Test-surface compatibility

Tests import via `postprocess.convert_X(...)`. To avoid rewriting ~603
tests at once, keep thin shims during migration: `postprocess.convert_X`
can default `ctx` to a module-level "current context" if none is passed.
Remove the shims once tests are updated (can be a follow-up; not on the
critical path).

## Scope boundaries

- **In:** the dataclass, `from_config`, per-family signature migration,
  removal of globals + the `sys.modules` alias, lesson-038 supersede note.
- **Out:** changing *what* any transform does. Pure plumbing.
- **Out:** a public library API. Reentrancy is the enabler; exposing a
  stable `convert_book(config) -> dict[str, str]` entry point is a
  *possible* follow-on, noted but not in scope.
- **Enables Phase 5.** Book-side overrides
  ([phase 5](phase-5-book-overrides.md)) are built on this context:
  `project_overrides.py` *contributes* to the `ConversionContext`
  (`EXTRA_REWRITES`, an optional `POST_CONVERT` hook) rather than mutating
  module globals. That is why Phase 5 is gated on Phase 3 — building book
  overrides on the globals would deepen the very state-mess this phase
  removes.

## Risks & mitigations

- **Large diff across 7 modules + the orchestrator.** → One family per
  PR, golden gate on each.
- **Subtle per-file counter resets.** `FileCounters` must be reset
  per-file exactly where `process_text` resets the globals today
  ([563–567](../../scripts/postprocess.py#L563-L567)). Add a golden case
  with two chapters whose exercise numbering must not bleed across files.

## Exit criteria

- No module-level mutable state on `postprocess.py`; `grep -rn "import
  postprocess" scripts/transforms/` returns nothing (or only type-only
  imports).
- The `sys.modules['postprocess']` alias is gone.
- Two books convert correctly in one process (a test that does exactly
  this — the reentrancy proof).
- Lesson 038 marked superseded with a pointer here.
