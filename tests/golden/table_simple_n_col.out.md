---
title: "Table Simple N Col"
---

# Optimizers

The lineage from plain SGD to AdamW is summarised below.

```{list-table}
:header-rows: 1
:caption: Lineage from plain SGD to AdamW.

* - Optimizer
  - Update rule
  - Reference
* - SGD
  - plain
  - standard
* - SGD+momentum
  - adds inertia
  - follow-up
* - Adam
  - per-param adaptive rates
  - widely used
* - AdamW
  - decoupled weight decay
  - current default
```

See {numref}`tab-optimizer-family` for the full table.
