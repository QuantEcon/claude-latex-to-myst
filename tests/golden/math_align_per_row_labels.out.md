---
title: "Math Align Per Row Labels"
---

# Bayesian Update

The Bayesian update for posterior mean and variance is

$$
\mu_{f,t+1} = \frac{S_{\epsilon}\,\mu_{f,t} + \varphi T_t S_{f,t} y_{t+1}}{S_{\epsilon} + (\varphi T_t)^2 S_{f,t}}
$$ (eq-bayes_mean)

$$
S_{f,t+1} = \frac{S_{\epsilon} \cdot S_{f,t}}{S_{\epsilon} + (\varphi T_t)^2 S_{f,t}}.
$$ (eq-bayes_var)

See {eq}`eq-bayes_mean` and {eq}`eq-bayes_var`.
