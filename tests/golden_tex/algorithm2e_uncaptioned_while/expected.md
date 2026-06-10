---
title: "Uncaptioned While"
---

```{prf:algorithm}
:nonumber:

- an initial state $X_0$ is given
- $t \leftarrow 0$
- while $t < T$ do
  - the controller observes the current state $X_t$ (-- per step)
  - the controller receives a reward $R_t$ that depends on the current state and action
  - using {eq}`eq-gp_mean` update `policy`
- end
```
