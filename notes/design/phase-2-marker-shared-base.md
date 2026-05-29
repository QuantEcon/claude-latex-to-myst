# Phase 2 — Marker shared base + hybrid boundary

**Status:** proposed · **Effort:** ~1–2 days · **Risk:** low · **Depends on:** Phase 1 gate

## Problem

Five of eight preprocess scripts are marker-pattern preprocessors
(tables, figures, algorithms, listings, description, enumerate). They
re-implement the same scaffolding. Concretely,
[`_apply_figure_markers.py`](../../scripts/_apply_figure_markers.py) and
`_apply_table_markers.py` share, near line-for-line:

- `_pandoc_batch_convert(cells)` — one pandoc call over a list of
  cells joined by `<!--CELL_N-->` sentinels, split on the way out
  ([figures version, lines 57–119](../../scripts/_apply_figure_markers.py#L57-L119)).
- The `~`-prefix guard against pandoc reading paragraph-leading `(a)` as
  math.
- The `` `<!-- -->`{=html} `` adjacency-artifact scrub.
- `base64` marker encode/decode.
- Blank-line-wrapped stream reassembly in source order
  ([lines 150–201](../../scripts/_apply_figure_markers.py#L150-L201)).

Each new structural construct currently re-pays this cost. The review
calls this out (§3); the code confirms it.

Separately, the **hybrid boundary is implicit**. The pipeline silently
runs both a marker resolver and an HTML-fallback for tables and figures
([`process_text`](../../scripts/postprocess.py#L588-L607)). Nobody has
written down "pandoc owns prose/math/inline-cites/refs; we own
structure." New contributors can't see the line, so it keeps moving by
accretion.

## Design

### 1. `scripts/markers/` shared base (or `transforms/_markers.py`)

Factor the common scaffolding so each preprocessor is "what's specific to
me" + a call into the base. Sketch:

```python
# markers/base.py
def pandoc_batch_convert(cells: list[str]) -> list[str]: ...   # the shared one
def encode_marker(kind: str, spec) -> str: ...                  # <!--KIND payload=b64-->
def decode_markers(text: str, kind: str): ...                   # iterator of (span, spec)
def reassemble(text, blocks, render) -> str: ...                # blank-line-wrapped, source order
```

Each preprocessor keeps only its construct-specific parts:
`find_<X>_blocks`, `parse_<X>_block`, and the spec → MyST `render`. Target
~50 LOC of specifics per construct (the review's estimate).

**Do not over-abstract.** Resist a "MarkerPlugin" base class with
registration and lifecycle hooks — that's the plugin-framework trap. Plain
functions + a shared module is enough. The win is *deduplication*, not
*extensibility*.

### 2. Sequencing relative to Phase 3

The marker base touches the *preprocess* scripts (which run before
pandoc, outside the `postprocess` global-state web). The
`ConversionContext` refactor (Phase 3) touches the *postprocess*
transforms. They're largely disjoint, so Phase 2 can land first and
cheaply, building confidence in the Phase-1 gate before the riskier
Phase 3.

### 3. Document the hybrid boundary (the cheap half of "track D")

Add a "Settled architectural decisions" entry to
[`CLAUDE.md`](../../CLAUDE.md) naming the boundary explicitly:

> **Pandoc owns inline prose, paragraph/inline math, native inline
> citations (`\cite`/`\citet`/`\citep`), and cross-ref plumbing (the
> `data-reference` recovery path). Everything structural — floats,
> tabulars, algorithms, listings, description/enumerate lists — is
> extracted to a marker pre-pandoc and decoded post-pandoc. New
> structural constructs follow the marker pattern; do not add a new
> post-pandoc HTML-scraping path.**

This makes the actual deprecation (retiring the HTML fallbacks) a
Phase-4 action, but locks the *intent* now so the boundary stops moving.

### 4. Scope-predicate conservatism (the #98 #3 lesson)

A marker preprocessor runs as a **separate pre-pandoc process** and
*cannot see* `postprocess` config state — `TIKZ_FIGURE_MAP`, `ENV_MAP`,
cross-ref routing all live on the `postprocess` module, populated by
`apply_config` in the post-pandoc run. So the preprocessor's decision
"should I marker-ize this block at all?" must be **purely syntactic**,
and it must be **conservative**: bail (return `None`, leaving the block
for the post-pandoc path) on any shape it cannot fully model.

GH #98 #3 is the cost of a non-conservative predicate:
`_apply_figure_markers` marker-ized a `\begin{figure}` wrapping a raw
`\begin{tikzpicture}`, scooped the tikz `{\footnotesize …}` node labels
in as sub-captions, and leaked them — when the post-pandoc
`TIKZ_FIGURE_MAP` override would have rendered it cleanly. The
preprocessor *couldn't know* the override existed; the fix is a syntactic
bail on `\begin{tikzpicture}`, mirroring the existing `subfigure` bail.

The shared base should make this explicit: a documented `bail_predicates`
list per construct, and a default stance of "bail unless fully modelled."
This is the structural antidote to over-specialization — the preprocessor
handles the shapes it provably handles and *defers* the rest, rather than
half-handling everything.

## Scope boundaries

- **In:** extract shared base; audit + document each preprocessor's bail
  predicates (add the missing `tikzpicture` bail for figures); migrate
  the two closest cousins (figure,
  table) onto it first; migrate the other three opportunistically;
  CLAUDE.md boundary note.
- **Out:** removing the HTML-fallback paths (that's Phase 4, gated on #94).
- **Out:** any behavior change. Golden output must be byte-identical
  before/after — this is a pure refactor, and Phase 1 is what proves it.

## Exit criteria

- `_pandoc_batch_convert` exists once, imported by all marker
  preprocessors.
- Golden corpus (both tiers) byte-identical pre/post refactor.
- CLAUDE.md states the pandoc/marker boundary.
