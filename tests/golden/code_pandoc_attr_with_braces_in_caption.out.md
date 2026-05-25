---
title: "Code Pandoc Attr With Braces In Caption"
---

# Listings

```{code-block} text
:name: lst-autodiff_euler
:caption: Autodiff Euler residual. The function \texttt{Pi} is the only model-specific code; a full implementation lives in notebook \texttt{02_Brock_Mirman.ipynb}.

def loss(params, x):
    return jnp.mean((residual(params, x))**2)
```
See {ref}`lst-autodiff_euler` for the residual.
