# Parity reports

When we run this pipeline against a new book, the result is captured here as
a markdown report. Each report records:

- What config was used
- How the pipeline performed (end-to-end success? errors?)
- What the diff looked like against any existing committed MyST output
- What transforms were missing or had to be added
- Any lessons captured during the run (linked to `lessons/`)

These reports are the empirical justification for changes to the pipeline.
When a new transform is added, the report that motivated it should be the
one that ages the best — it documents the original "broken vs. fixed"
state.

## Naming

`book-<short-name>-parity.md` — one per book. If the same book is tested
multiple times across pipeline revisions, append a date or revision suffix.

## Current reports

- [`book-dp2-parity.md`](book-dp2-parity.md) — extraction parity test against the
  originating project
- [`book-dp1-parity.md`](book-dp1-parity.md) — first cross-project parity test
