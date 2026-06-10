---
id: 046
title: "Structural parity is not render parity — only a real `myst build` catches emission bugs the markdown text can't show"
category: validation
tags: [myst-build, render-gate, commonmark, fence-info-string, heading-anchors, smoke-test]
source_project: book-dp1
status: codified
codified_in: scripts/build_smoke.py + scripts/validate_fixture.sh::--build (signal D)
severity: high
date: 2026-06-10
---

## Symptom

Every structural gate is green — 700+ unit/golden tests, `validate.py`
counts, the byte-identical `_snapshot` diff — yet the built book is broken.
In the PR #103 series, **five** distinct bugs shipped past all structural
gates and only surfaced in a real `myst build --html` of a regenerated book
(dp1 went from 0 to 152 build warnings before the catches):

1. **Stacked heading anchors** (`(a)=` `(b)=` above one heading): mystmd
   keeps ONE anchor per node — `label "sss-fsmdp" replaced with
   "ss-gfsmdp"` — and every ref to the dropped label dangles (#123).
2. **Backtick role in a backtick-fence info string**
   (`` ```{prf:proof} Proof of {prf:ref}`p-x` ``): CommonMark §4.5 forbids
   backticks in a backtick fence's info string, so the line is *not a fence
   opener* — the directive never opens and its closing fence opens a literal
   code block that swallows everything (~250 lines in ch_intro) to the next
   fence (#122).
3. **Pandoc bracketed spans** (`[iid]{.smallcaps}` from `\textsc`): mystmd
   doesn't implement them; the markup renders literally (#124).
4. **Directive re-shape broke a consumer override match**: starred-env
   `{math}` emission stopped `TIKZCD_INLINE_MAP`'s `$$ … tikzcd … $$`
   pattern matching, leaking tikzcd to KaTeX and losing the mapped figure —
   and the count drift it caused was *misread as an improvement* because it
   moved counts toward equality (PR #127).
5. **Dir-qualified figure paths** (`fig/foo.pdf`): convert.sh flattens
   assets to `output/figures/<basename>`, so the prefix always dangles
   (PR #128).

## Cause

The structural gates all inspect the markdown **text**. These bugs live in
the gap between text that *looks* valid and what the CommonMark parser /
mystmd's resolver actually do with it: fence-opening rules, one-label-per-
node resolution, unimplemented pandoc syntax, downstream consumer-override
regexes, and filesystem layout. No amount of text-level diffing can see
them, because the broken and "fixed" texts are both plausible markdown —
the failure only exists at parse/resolve/render time.

Two sharp platform facts worth remembering on their own:

- **CommonMark §4.5**: the info string of a *backtick* fence may not contain
  backticks. Any directive argument that can carry an inline role must not
  be emitted on a backtick fence line (use a body lead-in, or colon fences).
- **mystmd allows exactly one `(name)=` anchor per node.** Consecutive
  stacked anchors warn `label X replaced with Y` and the loser is dropped.
  Secondary labels must be resolved at convert time (alias-rewrite the refs
  to the surviving primary; see `scan_heading_label_aliases`).

## Fix

Codified as **signal (D)** in the fixture harness:

```bash
bash scripts/validate_fixture.sh all --against snapshot --build
# or directly:
python3 scripts/build_smoke.py --fixture fixtures/book-dp1 \
    --check tests/baselines/build-dp1.txt
```

`scripts/build_smoke.py` overlays `regen/*.md` onto a temp copy of the
book's worked-on `mystmd/` project, runs `myst build --html`, normalizes the
`⚠️`/`⛔` lines (numbers→N, temp dirs→TMPDIR, content hashes→HASH), and
diffs against the committed per-book baseline in
`tests/baselines/build-<book>.txt`. Any NEW line fails; vanished lines pass
with a re-baseline hint (`--write` after a reviewed run). The dp1 baseline
is **empty** — a zero-warning build is the pinned contract.

For pre/post pipeline comparisons (e.g. validating a large branch), build
the same regen with both pipelines via a git worktree and diff the
normalized profiles — that isolates exactly what the change does to build
health, independent of pre-existing noise.

## How to detect

- `bash scripts/validate_fixture.sh <book> --build` — the gate itself.
- The high-signal grep on any build log:
  `grep -E 'replaced with|target was not found|text is empty|unknown directive' build.log`
- Static pre-build catch for the #122 class (also in `validate.py` pass 3):
  `grep -nE '^ {0,3}\`{3,}\{[^}]+\}[^\n]*\`' *.md`
