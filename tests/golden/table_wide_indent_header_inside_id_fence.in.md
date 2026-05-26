# Wide-indent header + id-fence test

::: {#tab:seq_compare}
                          **RNN**            **LSTM / GRU**     **Transformer**
  ----------------------- ------------------ ------------------ ------------------------
  Hidden state            single $\h_t$      $\h_t$ and $C_t$   none per step
  Path length             $\mathcal{O}(T)$   $\mathcal{O}(T)$   $\mathcal{O}(1)$
  Parallelism             none               none               full

  : Comparison of sequence architectures across $\mathcal{O}(T^2)$ attention and unit-length paths.
:::

See {numref}`tab-seq_compare` for the comparison.
