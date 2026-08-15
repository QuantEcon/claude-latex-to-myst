---
title: "Approximation"
label: c-approx
---

(sec-vi)=
## Value Iteration
A numbered section. It must come out with a plain heading and no attribute block at all — the fix adds the block only where pandoc marked one.

## Summary {.unnumbered}
A starred section. Unnumbered in LaTeX, so it must not take a section number, and it must not advance the counter either: the next numbered section below is the *second*, not the third.

### Validation Protocol {.unnumbered}
Starred one level deeper. Same treatment, at any depth.

(sec-fr)=
## Further Reading {.unnumbered}
A starred section the author *also* labelled. Both channels are needed: the anchor so `\ref` resolves, and the class so it stays unnumbered.

(sec-pi)=
## Policy Iteration
The counter check. This is §1.2 — the starred sections between it and {ref}`sec-vi` contributed nothing.

Cross-references still resolve: {ref}`sec-fr` renders its title (a starred section has no number to show), while {ref}`sec-pi` renders a number.
