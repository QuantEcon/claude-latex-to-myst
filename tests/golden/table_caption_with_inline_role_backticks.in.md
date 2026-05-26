# Reproducer for the 8 silently-failing captioned tables

Pre-fix: 8 tables in the Deep-Learning book had captions containing inline-role backticks (`{ref}`, `{cite:t}`, `{numref}`). The 4-backtick `{table}` opener carried the caption as its argument, and MyST's argument parser mistook the role's backticks for inline-code-span delimiters — the directive failed to parse and the table collapsed to a paragraph in the AST.

::: {#tab:relobralo_hp}
  ---- ----
  H1   H2
  ---- ----
  a    b
  ---- ----

  : ReLoBRaLo hyperparameter sweep, following {cite:t}`bischof2025relobralo`. The grid spans rates in Chapter {ref}`ch-pinn` and crossover with {numref}`tab-other_methods`.
:::

Body refs: see {numref}`tab-relobralo_hp` for the hyperparameters.
