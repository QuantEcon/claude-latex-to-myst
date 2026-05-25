# Bayesian Update

The Bayesian update for posterior mean and variance is

$$\begin{align}
\mu_{f,t+1} &= \frac{S_{\epsilon}\,\mu_{f,t} + \varphi T_t S_{f,t} y_{t+1}}{S_{\epsilon} + (\varphi T_t)^2 S_{f,t}}, \label{eq:bayes_mean}\\
S_{f,t+1} &= \frac{S_{\epsilon} \cdot S_{f,t}}{S_{\epsilon} + (\varphi T_t)^2 S_{f,t}}. \label{eq:bayes_var}
\end{align}$$

See [\[eq:bayes_mean\]](#eq:bayes_mean){reference-type="ref" reference="eq:bayes_mean"} and [\[eq:bayes_var\]](#eq:bayes_var){reference-type="ref" reference="eq:bayes_var"}.
