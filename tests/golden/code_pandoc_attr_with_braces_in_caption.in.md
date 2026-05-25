# Listings

``` {#lst:autodiff_euler caption="Autodiff Euler residual. The function \texttt{Pi} is the only model-specific code; a full implementation lives in notebook \texttt{02_Brock_Mirman.ipynb}." label="lst:autodiff_euler"}
def loss(params, x):
    return jnp.mean((residual(params, x))**2)
```

See [\[lst:autodiff_euler\]](#lst:autodiff_euler){reference-type="ref" reference="lst:autodiff_euler"} for the residual.
