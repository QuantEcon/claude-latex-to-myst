---
title: "Algorithm Keyword Emphasis"
---

```{prf:algorithm} Value function iteration
:label: algo-vfi

1. input $v \in \RR^\Xsf$ and tolerance $\tau$
2. $\epsilon \leftarrow \tau + 1$
3. **while** $\epsilon > \tau$ **do**
   1. $v' \leftarrow Tv$
   2. $\epsilon \leftarrow \| v' - v \|$
   3. $v \leftarrow v'$
4. **end**
5. **return** a $v$-greedy policy $\sigma$
```

```{prf:algorithm} Howard policy iteration
:label: algo-hpi

1. input $\sigma \in \Sigma$ and tolerance $\tau$
2. **while** $\epsilon > \tau$ **do**
   1. $\sigma \leftarrow$ a $v$-greedy policy
3. **end**
4. **return** $\sigma$
```
