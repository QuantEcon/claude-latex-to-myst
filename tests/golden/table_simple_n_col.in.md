# Optimizers

The lineage from plain SGD to AdamW is summarised below.

::: center
  -------------- ------------- ------------------
  Optimizer      Update rule   Reference
  -------------- ------------- ------------------
  SGD            plain         standard

  SGD+momentum   adds inertia  follow-up

  Adam           per-param     widely used
                 adaptive
                 rates

  AdamW          decoupled     current default
                 weight decay
  -------------- ------------- ------------------

  : Lineage from plain SGD to AdamW.
:::

See {numref}`tab-optimizer-family` for the full table.
