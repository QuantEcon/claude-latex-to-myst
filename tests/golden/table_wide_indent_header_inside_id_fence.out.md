---
title: "Table Wide Indent Header Inside Id Fence"
---

# Wide-indent header + id-fence test

(tab-seq_compare)=
````{table} Comparison of sequence architectures across $\mathcal{O}(T^2)$ attention and unit-length paths.
:name: tab-seq_compare

```{list-table}
:header-rows: 1

* - 
  - **RNN**
  - **LSTM / GRU**
  - **Transformer**
* - Hidden state
  - single $\h_t$
  - $\h_t$ and $C_t$
  - none per step
* - Path length
  - $\mathcal{O}(T)$
  - $\mathcal{O}(T)$
  - $\mathcal{O}(1)$
* - Parallelism
  - none
  - none
  - full
```
````

See {numref}`tab-seq_compare` for the comparison.
