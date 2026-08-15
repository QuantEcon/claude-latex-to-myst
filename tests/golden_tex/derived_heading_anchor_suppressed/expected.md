---
title: "Derived Heading Anchor Suppressed"
label: preface
---

An unlabelled chapter: pandoc derives "preface" for the H1. Depth 1 is gated out of the suppression because `add_frontmatter` keys on the anchor to build the page `label:`.

(sec-vi)=
## Value Iteration
An author-labelled section. The slug is `sec:vi`, which pandoc could never derive from the title, so the anchor is promoted.

(sec-conv)=
## Convergence {.unnumbered}
A starred section that the author still labelled. Starred forces an attribute block, but the id inside it is the author's, so it is promoted.

## Background reading {.unnumbered}
A starred, unlabelled section. Pandoc mints "background-reading" from the title and only emits it because `.unnumbered` forces the attribute block. Nothing here is a cross-reference target, so no anchor.

## Exercises {.unnumbered}
Repeat this title in a second chapter and the derived anchors collide project-wide — the reported symptom.

(exercises-1)=
## Exercises {.unnumbered}
Pandoc's within-file dedup suffix. Unique by construction, so it never collides; suppressing it would not be identifier-neutral, so it is kept.

Refer back to {ref}`sec-vi` and {ref}`sec-conv` to confirm both author labels still resolve.
