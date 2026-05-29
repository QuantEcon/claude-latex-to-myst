---
title: "Algorithm Block"
---

# An algorithm

```{prf:algorithm} Value iteration
:label: algo-vi

- **Input:** initial guess $v_0$, tolerance $\epsilon$
- $k \gets 0$
- while $\|v_{k+1} - v_k\| > \epsilon$:
  - $v_{k+1} \gets T v_k$
  - $k \gets k + 1$
- return $v_k$
```
