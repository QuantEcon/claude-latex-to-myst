---
title: "Inline Equation"
---

````{prf:algorithm} Solving via Howard policy iteration
:label: algo-hpowb

1. input $\sigma_0 \in \Sigma$, set $k \leftarrow 0$ and $\epsilon \leftarrow 1$
2. while $\epsilon > 0 $ do
   1. $h_k \leftarrow $ the fixed point of $\hat T_{\sigma_k}$
   2. $\sigma_{k+1} \leftarrow $ an $h_k$-greedy policy, satisfying

      ```{math}
      :enumerated: false

      \sigma_{k+1}(w, e) \in \argmax_{w' \in \Gamma(w, e)} \left\{ (1-\beta) r(w, w', e)^\alpha + \beta h_k(w')^\alpha \right\}^{1/\alpha}
      ```

   3. $k \leftarrow k + 1$
3. end
4. return $\sigma_{k-1}$
````
