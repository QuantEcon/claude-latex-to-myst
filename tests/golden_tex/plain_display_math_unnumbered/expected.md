---
title: "Plain Display Math"
---

Plain double-dollar display math (unnumbered in LaTeX):

```{math}
:enumerated: false

Tf = e \vee (c + \beta Pf) \leq e \vee (c + \beta Pg) = Tg.
```

Bracket display math (also unnumbered):

```{math}
:enumerated: false

a = b + c
```

A numbered equation keeps its number:

$$
x = y + z
$$

A numbered, labelled equation keeps its number too:

$$
p = q
$$ (eq-foo)

Bracket display math wrapping an inner alignment stays unnumbered:

```{math}
:enumerated: false

\begin{aligned}
u &= v \\
w &= z
\end{aligned}
```
