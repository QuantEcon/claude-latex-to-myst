# Architecture evolution — design docs

Outcome of the deep implementation review (input: [`../DESIGN-REVIEW.md`](../DESIGN-REVIEW.md)).
These docs turn that review into a phased plan. The guiding goal is
**support more general conversion without over-specializing on edge
cases** — and, equally, without over-generalizing into a rewrite.

## The two failure modes we're steering between

- **Over-specialization** (the visible risk): every new book adds a
  narrow regex / a new lesson. ~30 of 43 lessons are pandoc-emission
  quirks. Left unchecked, the pipeline becomes a pile of book-specific
  patches.
- **Over-generalization** (the silent risk): rewriting pandoc as a
  custom LaTeX AST, or building a plugin framework, in the name of
  "generality." Multi-quarter cost, new bug surface, no payoff. The
  review already dismissed the custom AST; see
  [`phase-4-surface-reduction.md`](phase-4-surface-reduction.md) for the
  decision record.

The antidote to both is the same: **make the hybrid boundary explicit,
thread state cleanly, and guard every change with a real end-to-end
gate.** That shrinks surface instead of growing it.

## The parity objective (why we keep three real books)

Running parallel to the phases is a standing objective: **get close to
parity across all three real-world fixtures** (`book-dp1`, `book-dp2`,
`book-dp-deep-learning`). Synthetic cases can't supply the translation
complexity real books do, so the books are the benchmark — and every gap
closed gets a `golden_tex` reproducer so the corpus grows as understanding
does. Parity is aspirational: the worked-on `mystmd/` on each
`mystmd-conversion` branch has hand-edits the deterministic tool won't
reproduce, so "close / only documented drift" is the bar, not byte-equality.

Validation therefore uses **two baselines**, and they must not be confused:

- a **pinned snapshot of current tool output** per book — the
  refactor-safety gate; behavior-preserving phases must keep regen
  byte-identical to it (tool-vs-tool, always achievable);
- the **worked-on `mystmd/`** — the parity *target*, a gap to drive down,
  never a hard gate and never overwritten by the tool.

The fixture-validation harness (`scripts/validate_fixture.sh`, added with the
common-fixture-validation work) implements both (`--against snapshot` for the
gate, default for the parity gap). Because safety rides on the snapshot,
parity is pursued *across* the refactoring, not as a precondition.

## Phases (priority order)

Each phase is a self-contained unit of work with its own design doc,
scope estimate, and exit criteria. Later phases assume earlier ones.

| Phase | Track | Why this order | Doc |
|------:|-------|----------------|-----|
| 1 | Validation gate + CI | Safety net. Guards every refactor below; would have caught #96. Cheapest, highest urgency. | [phase-1](phase-1-validation-gate.md) |
| 2 | Marker shared base + hybrid boundary | Low-risk consolidation of confirmed duplication; documents the pandoc/marker line so it stops accreting silently. | [phase-2](phase-2-marker-shared-base.md) |
| 3 | `ConversionContext` (state threading) | Deepest generality win — makes the pipeline reentrant and kills the lesson-038 global-state class. Risky, so it runs *after* the Phase-1 gate exists. | [phase-3](phase-3-conversion-context.md) |
| 4 | Surface reduction (subfigure #94 → retire HTML fallbacks) | Depends on Phases 2–3 and on #94. Removes the dual code path per construct. Plus the custom-AST decision record. | [phase-4](phase-4-surface-reduction.md) |
| 5 | Book-side overrides + graduation rule | Depends on Phase 3 (overrides feed `ConversionContext`, not globals). Gives book-specific *programmatic* edge cases a home, with a counting rule for when they graduate into the generic pipeline. | [phase-5](phase-5-book-overrides.md) |

## What is explicitly NOT in this plan

- No custom LaTeX AST (decision record in phase 4).
- No plugin framework. Phase 3 makes ordering explicit; it does not make
  the pipeline arbitrarily extensible. Phase 5's book-side overrides are a
  **closed** surface (a fixed set of slots + one named hook), explicitly
  *not* a registration/lifecycle framework.
- No LLM calls in the pipeline (settled in CLAUDE.md).

## Status

- **Phase 1 — ESCALATED to urgent (2026-05-29).** GH #98 (four
  figure-marker regressions in a dp2/dp1 regen) is the over-specialization
  risk *materializing*: a construct migrated to the marker pattern shipped
  with parser-completeness gaps because there was no `.tex`-rooted
  differential gate. Verdict from the #98 analysis: **not a redesign** —
  the regressions are localized to the 15-commit figure-marker work, and
  the marker architecture is sound. What's missing is its safety
  complement (Phase 1). Recommend **freezing further fallback→marker
  migrations until the gate lands.**
- Phases 2–5 remain **proposed**, not started. Phase 5 (book-side
  overrides) was added 2026-05-29 after the design discussion settled the
  "where do book-specific edge cases live?" question — answer: a closed
  `project_overrides.py` surface, governed by the graduation rule, built
  on Phase 3's `ConversionContext`.

ROADMAP.md tracks them under "Architecture evolution." This directory is
the design substrate; update the relevant doc when a phase starts or its
design shifts.

### Diagnostic principle (from #98)

The marker pattern trades *pandoc-emission bugs* (open-ended, invisible
until render, un-lockable) for *parser-completeness bugs* (a
re-implemented parser that starts incomplete). The trade is favourable —
parser bugs are finite, diffable, and lockable by a fixture — **but only
with a differential gate.** Without it, the project pays the
architecture's cost (re-implemented parsers) without its benefit (safe
migration), and every update cycle feels like a regression. The fix is to
finish the architecture (add the gate), not to abandon it.
