---
title: "Full Minichapter Kitchen Sink"
label: ch-kitchen
---

A small integration test combining several transform families.

(sec-one)=
## Section One
The Bellman equation is

$$
V(x) = \max_a \{ r(x,a) + \beta \mathbb{E} V(x') \}.
$$ (eq-bellman)

We use {cite:p}`bellman1957` as the foundational reference. The contraction property is established in {prf:ref}`thm-contract`.

(sec-two)=
## Section Two
```{prf:theorem}
:label: thm-contract

The Bellman operator is a contraction.
```


See {ref}`sec-one` for the equation and {eq}`eq-bellman` specifically.
