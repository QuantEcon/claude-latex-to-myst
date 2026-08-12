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
closed gets a `tests/golden_tex/` reproducer so the corpus grows as
understanding does. Parity is aspirational: the worked-on `mystmd/` on each
`mystmd-conversion` branch has hand-edits the deterministic tool won't
reproduce, so "close / only documented drift" is the bar, not byte-equality.

Validation therefore uses **two baselines**, and they must not be confused:

- a **pinned snapshot of current tool output** per book — the
  refactor-safety gate; behavior-preserving phases must keep regen
  byte-identical to it (tool-vs-tool, always achievable);
- the **worked-on `mystmd/`** — the parity *target*, a gap to drive down,
  never a hard gate and never overwritten by the tool.

The fixture-validation harness (`scripts/validate_fixture.sh`, introduced in
the common-fixture-validation PR #101 — not yet on `main` if you're reading
this before it merges) implements both (`--against snapshot` for the gate,
the default `--against baseline` for the parity gap). Because safety rides on
the snapshot, parity is pursued *across* the refactoring, not as a precondition.

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
| 6 | Deep-Learning parity pass | Added during PR #103 to prove the architecture generalizes to a third, different book. tikz figure-caption math preservation + marker-aware `validate.py`; DL parity 166→20 diff lines. | [phase-6](phase-6-dl-parity.md) |

## What is explicitly NOT in this plan

- No custom LaTeX AST (decision record in phase 4).
- No plugin framework. Phase 3 makes ordering explicit; it does not make
  the pipeline arbitrarily extensible. Phase 5's book-side overrides are a
  **closed** surface (a fixed set of slots + one named hook), explicitly
  *not* a registration/lifecycle framework.
- No LLM calls in the pipeline (settled in CLAUDE.md).

## Status

**All six phases LANDED in PR #103** (one branch, one commit per phase, each
validated against the pinned refactor-safety snapshot before the next). Each
phase doc carries a "LANDED" banner with its result. Highlights: the Phase-1
`.tex`-rooted gate + CI is in place; the marker scaffolding is shared once
(Phase 2); run state is a threaded `ConversionContext` with no module globals
(Phase 3); `#94` subfigure markers + the "no custom AST" record landed
(Phase 4); the closed `project_overrides.py` surface + graduation rule landed
(Phase 5); and the Deep-Learning parity pass (Phase 6) drove DL's diff vs the
worked-on baseline 166→20 lines, proving the architecture generalizes to a
third, different book.

The **forward plan** (consolidation of the Phase-3/5 shims, validator
honesty for split-source books, adoption + parity) lives in
[ROADMAP.md](../../ROADMAP.md). This directory is the design substrate;
new large efforts get a design doc here before implementation.

### Diagnostic principle (from #98)

The marker pattern trades *pandoc-emission bugs* (open-ended, invisible
until render, un-lockable) for *parser-completeness bugs* (a
re-implemented parser that starts incomplete). The trade is favourable —
parser bugs are finite, diffable, and lockable by a fixture — **but only
with a differential gate.** Without it, the project pays the
architecture's cost (re-implemented parsers) without its benefit (safe
migration), and every update cycle feels like a regression. The fix is to
finish the architecture (add the gate), not to abandon it.
