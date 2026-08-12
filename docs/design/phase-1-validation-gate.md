# Phase 1 — Validation gate + CI

**Status:** LANDED (architecture-evolution branch, commit 1/5) · **Effort:** ~1–2 days · **Risk:** low · **Unblocks:** Phases 2–4

> **Landed.** `.github/workflows/test.yml` (push + PR, pinned pandoc),
> `tests/golden_tex/` seeded from the lesson catalogue (16 new cases +
> `LESSON_COVERAGE.md`), the §1b differential gate
> (`tests/test_marker_differential.py`, lesson 044), and the per-book count
> baseline (`scripts/count_baseline.py` + `tests/baselines/*.json`). Verified:
> a reverted #98 #1 width fix turns 5 gates red (3 golden_tex + both
> differential tests); snapshot gate behavior-preserved ×3.

> **Escalation (2026-05-29, GH #98).** A dp2/dp1 regen against the
> figure-marker work (#95/#97) surfaced four shipped regressions — dropped
> `:width:` (31 figures), leading-space captions (66), leaked TikZ node
> text, and a dropped image when `\includegraphics`'s path sits on the
> next line. **All four are parser-completeness gaps in the new marker
> path** that a `.tex`-rooted differential gate would have caught
> pre-merge. This is no longer a hypothetical "would have caught #96" —
> it is the recurring cost of migrating constructs to the marker pattern
> without a gate. **Recommendation: freeze further fallback→marker
> migrations (Phase 4 / #94) until this gate exists.**

## Problem

The #95 → #96 → #98 trajectory: synthetic e2e tests passed while the
consumer books (`book-dp-deep-learning`, then `book-dp2`/`book-dp1`)
regressed. There is currently **no CI** (`.github/workflows/` does not
exist) and **no automated end-to-end gate rooted in `.tex`**.

The deeper pattern (see GH #98 analysis): the marker pattern trades
*pandoc-emission bugs* (open-ended, invisible until render) for
*parser-completeness bugs* (a re-implemented parser that starts
incomplete). That trade is favourable **only** with a differential gate —
parser bugs are finite, discoverable by diffing, and lockable by a
fixture; pandoc-emission bugs were none of those. Without the gate, the
project pays the architecture's cost (re-implemented parsers) without its
benefit (safe migration). #98's four regressions are what that feels like.

The existing golden corpus ([`tests/golden/`](../../tests/golden/)) is the
right shape but the wrong tier: its fixtures are `*.in.md → *.out.md`,
i.e. they start from **pandoc output** and exercise `process_text` only.
The entire preprocess → pandoc → marker-decode boundary — where #95/#96
and most of the lesson catalogue live — is untested end-to-end. A
`.tex`-rooted tier is the gap.

The full consumer books under [`fixtures/`](../../fixtures/) are
gitignored clones (megabytes, external repos). They cannot be a CI
dependency. Decision (taken with the user): **curated golden corpus**,
self-contained in the repo.

## Design

Two pieces: a `.tex`-rooted golden tier, and a CI workflow that runs it.

### 1. `.tex`-rooted golden tier

A new corpus that exercises the *whole* pipeline, not just `process_text`.

```
tests/golden_tex/
  <case>/
    input.tex            # hand-authored, small, one construct family
    config.yaml          # minimal per-case config (or a shared default)
    expected.md          # committed golden output
```

A test (`tests/test_golden_tex.py`) runs, per case: `preprocess.sh` →
`pandoc` → `postprocess.py` (i.e. the real `convert.sh` stages, or a
thin Python harness that calls the same stage functions), then diffs the
result against `expected.md`. Byte-diff for exactness; on mismatch, print
a unified diff and fail.

**Seed the corpus from the lesson catalogue.** Every codified lesson that
describes a pandoc-emission quirk should have a minimal `.tex` reproducer
here. This is also the answer to the review's "are lessons
machine-actionable?" question — a lesson without a golden_tex case is a
lesson that can silently regress. Start with the ~14 bug classes in
DESIGN-REVIEW §1 (tables/figures/citations/refs).

**Requires pandoc on CI** — pin a version (pandoc output is
version-sensitive; pin to avoid golden churn on runner upgrades).

### 1b. Differential migration-parity gate (the #98 lesson)

A golden corpus catches regressions against a *frozen expected output*.
But the recurring failure mode is subtler: **migrating a construct from
its HTML-fallback path to a marker path silently drops features the old
path had** (#98 #1 width, #98 #3 tikz-body suppression). A from-scratch
golden file can't catch that — at migration time there's no "before" to
diff against, and the author writes the "expected" from the new path's
(buggy) output.

So when a construct is migrated fallback→marker, add a **differential
check**: for a corpus of real `.tex` figure/table blocks, run *both* the
old fallback path and the new marker path and assert the new output is
equal-or-explicitly-better. Where "better" is claimed, the diff is
reviewed and pinned as the new golden. This is a temporary scaffold that
lives only during a migration (it can be deleted once the fallback is
retired in Phase 4), but it is exactly the gate that would have caught
all four #98 regressions before merge.

Concretely for #98: a corpus of the dp1/dp2 figure shapes —
`[width=…\textwidth]`, path-on-next-line, raw-`tikzpicture`-with-override,
plain `\includegraphics` — diffed old-vs-new would have flagged width
loss, the dropped image, and the leaked node text immediately.

### 2. Structural-count gate (no full build needed)

[`validate.py`](../../scripts/validate.py) already does count-based +
cross-ref-resolution + type-compatibility checks. Phase 1 wires it into
the gate: for each golden_tex case (and optionally for committed consumer
fixtures), assert `validate.py` exits 0. This catches "figure silently
dropped" without needing `myst build`.

### 2b. Per-book count baseline (use the three real books cheaply)

The full consumer books can't go in CI (gitignored, megabytes), but their
*`validate.py` output can*. Commit a tiny per-book `baseline.json` —
figure/table/cite/ref counts plus the cross-ref-resolution result — for
each of the three fixtures (`book-dp-deep-learning`, `book-dp1`,
`book-dp2`). A label-gated CI job clones the fixture, regenerates the
counts, and diffs against the committed baseline. The baseline file is
small enough to version even though the book isn't.

This is the cheap complement to the two diff-based tiers, and the tiers
catch different failures: **counts catch *drops*** (#98 #4, the dropped
image — a count change), while the **byte-diff golden_tex** and the
**§1b old-vs-new differential** catch *attribute degradation* (#98 #1
width, #98 #3 leaked tikz text — same count, worse content). All three
are needed; none subsumes the others.

### 3. CI workflow

`.github/workflows/test.yml`:
- Job 1 (every PR): `uv sync` → `pytest` (the existing ~603 unit tests +
  both golden tiers). Pin pandoc.
- Job 2 (optional, nightly or label-gated): clone the consumer books and
  run `convert.sh` + `validate.py` against them as a deeper, allowed-to-be-
  flaky check. Not a merge blocker; the curated corpus is the blocker.

## Scope boundaries

- **In:** golden_tex harness, ~15–25 seeded cases, CI workflow, pandoc pin.
- **Out:** running `myst build` in CI (slow, separate concern). Out: any
  transform changes — Phase 1 is pure test/infra.

## Exit criteria

- `.github/workflows/test.yml` green on `main`.
- Every codified pandoc-quirk lesson has a `golden_tex` reproducer, or is
  explicitly noted as not-reproducible.
- A deliberate regression in a marker preprocessor fails CI (verify by
  reverting #96's fix on a scratch branch and watching it go red).

## Open questions

- Shared default `config.yaml` vs per-case? Lean shared default with
  per-case overrides only where a case needs them.
- Harness: call `convert.sh` as a subprocess, or call the stage functions
  in-process? In-process is faster and gives better tracebacks, but
  `convert.sh` is what consumers actually run. Probably a thin in-process
  harness that mirrors `convert.sh` stage-for-stage, with one smoke test
  that runs `convert.sh` itself to keep them honest.
