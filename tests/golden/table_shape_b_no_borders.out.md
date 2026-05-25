---
title: "Table Shape B No Borders"
---

# Optimizers

Tables emitted by pandoc from ``\begin{table}\begin{tabular}...\end{tabular}
\caption{...}\label{...}\end{table}`` lack ``\toprule`` / ``\bottomrule`` —
pandoc inserts only the header separator. The header row sits at the
table's indent immediately above the dash-rule, with the body below.

````{table}

Lineage from plain SGD to AdamW.

```{list-table}
:header-rows: 1

* - Optimizer
  - Update rule
  - Reference
* - SGD
  - plain SGD
  - standard
* - SGD+momentum
  - adds inertia
  - follow-up
* - Adam
  - per-param adaptive
  - widely used
* - AdamW
  - Adam plus decay
  - current default
```
````

See {numref}`tab-optimizer-family` for the table above.
