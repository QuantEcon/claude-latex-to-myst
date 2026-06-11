---
title: "Uncaptioned While"
---

```{prf:algorithm}
:nonumber:

1. an initial state $X_0$ is given
2. $t \leftarrow 0$
3. while $t < T$ do
   1. the controller observes the current state $X_t$ (– per step)
   2. the controller receives a reward $R_t$ that depends on the current state and action
   3. using {eq}`eq-gp_mean` update `policy`
4. end
```
