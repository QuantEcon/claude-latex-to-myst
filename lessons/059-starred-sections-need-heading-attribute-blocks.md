---
id: 059
title: "`\\section*` is unnumbered in LaTeX and pandoc says so with a `.unnumbered` class — dropping it lets book-mode numbering number the heading *and* advance the counter, and re-emitting it needs a renderer that parses heading attribute blocks"
category: post-processing
tags: [headings, numbering, starred-sections, unnumbered, attribute-block, renderer-floor, qe-v10]
source_project: Deep_Learning_for_Solving_And_Estimating_Dynamic_Economic_Models (external)
status: codified
codified_in: scripts/transforms/frontmatter.py::convert_section_labels
severity: medium
date: 2026-08-15
---

## Symptom

Every chapter of the deep-learning book ended with two sections that carried
numbers the printed book doesn't give them:

```
3.6.1  Validation Protocol      <- \subsection*{Validation Protocol}
3.7    Further Reading          <- \section*{Further Reading}
3.8    Exercises                <- \section*{Exercises}
```

24 headings across the book. In book-dp2 the same bug numbered
`\section*{Summary}` as §1.5 and pushed `Chapter Notes` to §1.6, against the
PDF's §1.5 — which shows the *second* half of the damage: a wrongly-numbered
heading also **advances the counter**, so it renumbers its numbered siblings.

## Cause

Pandoc gets this right. `\section*{Summary}` reaches the post-processor as

```markdown
## Summary {#summary .unnumbered}
```

— the `.unnumbered` class is pandoc faithfully recording that the command was
starred. `convert_section_labels` read the *first* token out of that
attribute block (the slug, for the `(label)=` target) and discarded
everything after it, so the class never reached the renderer and book-mode
numbering treated the heading like any other.

The reason it was discarded is the interesting part, and it is the reason
this sat open for two months: **there was no correct MyST to emit.** Until
`qe-v10` the renderer had no per-heading numbering control at all. Probes on
`qe-v8` and again on `qe-v9` confirmed both candidate syntaxes failed —
`## Summary {.unnumbered}` leaked the whole brace block into the heading
*text* and its derived slug, and a `+++ {"enumerated": false}` block-break
set the flag on `block.data` where it never propagated to the heading node.
Keeping the class would have *degraded* the page, so the converter dropped
it and the issue was routed Tier-3 (see CLAUDE.md's tier rule: valid-but-
unrendered ⇒ file upstream, never work around it here).

## Fix

Re-emit the numbering channel, and only that channel:

```python
attrs = m.group(3).split()
slug = attrs[0]
suffix = ' {.unnumbered}' if '.unnumbered' in attrs[1:] else ''
```

appended to both returns of `replace_header`. `qe-v10`
(QuantEcon/mystmd#89, from the #68 ask) parses a pandoc-style attribute
block on a heading and reads `.unnumbered` as `enumerated: false`, which
mystmd's `shouldEnumerateNode` already honours end-to-end: the heading takes
no number, `addTarget` skips `incrementCount` so the counter doesn't move,
and the target and TOC entry survive.

Four things that look like details and are not:

**1. It rides the *suppression* branch, not the label branch.** All 25
affected headings in the three books have a pandoc-*derived* slug, so every
one takes the #194 branch that drops the attribute block wholesale.
Re-emitting only where an anchor is promoted would have fixed **zero** of
them. The two changes touch the same three lines and are easy to reason
about backwards.

**2. Don't move the slug into the block.** `qe-v10` accepts `{#id}` too, so
`## Summary {#sec-summary .unnumbered}` is tempting. Emitting it *alongside*
the existing `(label)=` target line makes mystmd warn `label "x" replaced
with "y"` and dangles refs to the loser. Keep the target line; add only the
class.

**3. Emit only `.unnumbered`, and assemble the block rather than passing
pandoc's through.** Be precise about what the parser rejects, because the
obvious guess is wrong: an *unfamiliar class* is **accepted** and carried as
an inert `class` attribute (`{.myclass}` → `class: "myclass"`, still
numbered), and so is `.unlisted`. What it rejects is a token of an
unrecognized **kind** — `{not-a-class}`, `{foo=bar}` — and then it abandons
the whole block and leaves the braces as literal text in the title. So the
argument for emitting only `.unnumbered` is not safety, it is that nothing
downstream gives another class meaning and pandoc attaches nothing else here
anyway (measured across all three books: the block is always exactly
`{#slug}` or `{#slug .unnumbered}`). Assembling from a fixed vocabulary is
what keeps the reject case unreachable.

**4. The leading space in `' {.unnumbered}'` is load-bearing.** The
renderer's pattern is `/(?:^|[ \t])\{([^{}]+)\}[ \t]*$/` — the brace must be
preceded by whitespace or start the line. Emit `## Title{.unnumbered}` and it
is not an attribute block at all: the braces stay in the title *and* the
heading is still numbered, which is both failure modes at once. Verified
against a real build; pinned by
`test_section_label_suffix_keeps_its_leading_space`.

## The renderer floor is the unforgiving kind

This is the second converter behaviour to require a specific fork version,
and the two fail *differently* — worth separating when proposing a third:

| Coupling | On an older renderer |
|---|---|
| #186 / `qe-v9` (per-row `align` numbering) | **Forgiving** — the block takes one number instead of several. The fix is silently forfeited. |
| #160A / `qe-v10` (heading attributes) | **Not forgiving** — `{.unnumbered}` renders as literal text in the title and pollutes its slug. Visible corruption. |

So the converter change and the `MYSTMD_REF` bump must land in one commit,
and the floor has to be stated where consumers actually look (README,
`docs/getting-started.md`, and `convert.sh`'s missing-`myst` warning), not
only in CI.

## Two things the fix does *not* reach

**`\chapter*` under `absorbed` frontmatter.** The H1 is lifted into the YAML
block, so there is no heading node left to carry a class. Five such pages
across dp2 and the deep-learning book get their unnumbered rendering from
the `myst.yml` TOC instead. Nothing regresses — the suffix is simply
discarded with the heading — but `\chapter*` semantics are not expressible
on that path. Under `standalone` the heading stays in the body and the class
does apply.

**A heading title that genuinely ends in a brace group** is now at the
renderer's mercy, and this is a property of the *floor bump*, not of the
converter change: `## Rates {.5}` parses `.5` as a class and the braces
vanish from the title. `## The set {1, 2, 3}` is safe (the tokenizer rejects
it and leaves it literal), and no heading in any of the three books ends in
a brace group at all — but a book whose section titles do will meet this.

## Prevention

- A pandoc attribute block is **data the reader recovered**, not noise.
  Before discarding a token from one, check whether the target format has
  gained a way to express it — #160A existed only because the answer was
  "no" for two renderer versions and nobody re-asked.
- When a fix is blocked on the renderer, **re-probe on the current pin
  before re-deriving the analysis.** This issue accumulated four rounds of
  the same investigation; each was recorded on the thread with the version
  it was run against, which is what made the fifth round cheap.
- `$`-anchored `postprocess.rewrites` that target a heading line now need to
  allow for a trailing attribute block. Noted in `config.example.yaml`.

## Related

- [058](058-derived-heading-slugs-must-not-become-anchors.md) — the same
  three lines of `convert_section_labels`, and the branch this fix had to
  ride. 058 is why the attribute block is dropped rather than promoted; 059
  is why part of it has to come back.
- [057](057-pass-row-numbering-envs-through-to-the-renderer.md) — the same
  shape one layer down: stop compensating once the renderer can do the job.
  057 is the *forgiving* version of the renderer-floor tradeoff.
