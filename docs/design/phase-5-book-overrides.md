# Phase 5 — Book-side overrides + the graduation rule

**Status:** LANDED (architecture-evolution branch, commit 5/5) · **Effort:** ~1–2 days · **Risk:** low–medium · **Depends on:** Phase 3 (`ConversionContext`)

> **Landed.** `load_overrides` now reads the **closed** `project_overrides.py`
> surface into the `ConversionContext`: `TIKZ_FIGURE_MAP` / `TIKZCD_INLINE_MAP`
> (already supported), `EXTRA_REWRITES` (compiled and *appended* to
> `ctx.postprocess_rewrites`), and one optional `POST_CONVERT(text, stem, ctx)`
> hook (held on `ctx.post_convert`, invoked once at a single documented point
> at the end of `process_text`). The `project_overrides:` config key is the
> preferred name; `tikz_overrides:` is retained as an alias (same loader,
> filename-agnostic). Everything *contributes* to the context — no module
> globals (Phase 3). Behavior-preserving: snapshot byte-identical ×3 (no
> fixture uses the new attributes yet). Proven on a real book: relocating a
> dp1 preface `**heading** → ## H2` rewrite from `config.postprocess.rewrites`
> into the override's `EXTRA_REWRITES` left dp1 regen **byte-identical**
> (the override reproduces existing behavior from a cleaner home). Golden
> case `post_convert_fence_aware` + `tests/test_project_overrides.py` prove
> the hook runs and is fence-aware (doesn't corrupt a code block). The
> graduation rule is already in CLAUDE.md (PR #100).

## Problem — the missing tier for book-specific edge cases

The project's working rule (CLAUDE.md) is "rare edge case → capture a
lesson, leave the pipeline alone; affects ≥2 books → codify in the
pipeline." That's a good rule, but today a *book-specific* fix has only
three places to live, and all three are bad:

1. **A hand-edit to the converted markdown** — lost on the next
   `convert.sh` re-run. The pipeline is re-runnable by design, so any
   hand-edit is a fix with a half-life.
2. **A `config.yaml` rewrite** — declarative regex only. Fine for
   string-substitution edge cases; useless when the fix needs to *parse*
   anything or make a structural decision.
3. **Upstream into `postprocess.py`** — exactly the over-specialization
   the architecture is trying to avoid. One book's quirk becomes every
   book's maintenance surface.

So there is a **missing tier**: book-specific *programmatic* edge cases
that need code but must not pollute the generic pipeline. The seam for it
already exists — [`tikz_overrides.py`](../../scripts/postprocess.py#L277)
is a book-side Python file loaded by `load_overrides` — but it is
hard-wired to harvest only `TIKZ_FIGURE_MAP` / `TIKZCD_INLINE_MAP`. The
architectural question is not "should book-side code exist" (it does) but
**how wide is that seam, and what is the rule for graduating out of it.**

## Design

### 1. Generalize `tikz_overrides.py` → `project_overrides.py`

Widen the existing override file into a book-side `project_overrides.py`
with a **closed** set of extension points. Not a plugin framework — a
single documented file the loader reads for a fixed, small set of
optional attributes:

```python
# <book>/mystmd/project_overrides.py
TIKZ_FIGURE_MAP   = { ... }          # already supported
TIKZCD_INLINE_MAP = { ... }          # already supported
EXTRA_REWRITES    = [ (pat, repl), … ]   # extra postprocess rewrites, book-only
POST_CONVERT      = None             # optional: callable(text, stem, ctx) -> text
```

The loader reads attributes that are present and ignores the rest. The
**closed** quality is the whole point: there is no registration API, no
hook ordering, no lifecycle — just a fixed handful of slots and at most
one named insertion point (`POST_CONVERT`, run at a single documented
position in `process_text`). This is the line between the
*override file* we want and the *plugin framework* the project has
already declined (ROADMAP "won't add a hooks framework"; phase 2 "resist
a MarkerPlugin base class").

### 2. The graduation rule (the over-/under-specialization steering)

This is the conceptual payload, more important than the mechanism:

> **One book needs it → it lives in that book's `project_overrides.py`.
> A second book needs it → it graduates into the generic pipeline, with
> a lesson and a golden case.**

This turns "is this transform too book-specific?" from a recurring
judgment call into a counting rule, and it keeps `postprocess.py` generic
*by construction*: nothing book-specific can accrete there, because the
first home for any one-book fix is book-side. It is the same explicit
hybrid the rest of the plan commits to — pushed down one level, from
"where does structure get parsed (pandoc vs. marker)" to "where do
edge cases live (book vs. tool)."

### 3. Why this is gated on Phase 3 (`ConversionContext`)

A book override must *contribute* state, not *mutate* it. Today the only
way to inject behaviour is to mutate `postprocess`'s module globals —
which is precisely the lesson-038 trap Phase 3 removes. Building book
overrides on top of the globals would deepen the mess Phase 3 is about to
delete.

After Phase 3, the clean shape falls out for free: the override file
*contributes to* the `ConversionContext` (`EXTRA_REWRITES` extend
`ctx.postprocess_rewrites`; `POST_CONVERT` is held on `ctx` and called at
one point), never touching a global. So **build the mechanism during or
immediately after Phase 3, not before it.** The *policy* (the graduation
rule) can be written into CLAUDE.md now — and is.

### 4. Conservatism mirrors the marker-preprocessor stance

Like the marker preprocessors (phase 2 §4), a `POST_CONVERT` hook should
be **fence-aware and conservative** — it runs on already-converted MyST,
so it must respect code fences / math regions and bail on shapes it can't
model, rather than blunt-regex the whole document. The closed surface
makes this easy to document: there is exactly one hook to get right.

## Scope boundaries

- **In:** generalize the loader to read `project_overrides.py` with the
  closed attribute set; thread `EXTRA_REWRITES` + `POST_CONVERT` through
  `ConversionContext`; document the graduation rule (done in CLAUDE.md);
  migrate the existing tikz consumers to the new filename (keep
  `tikz_overrides.py` working as an alias for one release).
- **Out:** any open-ended hook/registration framework, multiple insertion
  points, or hook ordering. If a second insertion point is ever needed,
  that is a signal the construct should graduate into the pipeline, not
  that the override surface should grow.
- **Out:** LLM calls in the override file — the determinism rule still
  holds; `project_overrides.py` is deterministic Python like everything
  else in the pipeline.

## Exit criteria

- `load_overrides` reads a documented, closed `project_overrides.py`
  surface; `tikz_overrides.py` still loads (aliased) for one release.
- `EXTRA_REWRITES` and `POST_CONVERT` flow through `ConversionContext`,
  not module globals.
- CLAUDE.md states the graduation rule (one book → override; second book
  → pipeline + lesson + golden case).
- A golden case proves a book-side `POST_CONVERT` runs and is
  fence-aware (does not corrupt a code block).
