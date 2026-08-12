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
- [`book-dp-deep-learning-parity.md`](book-dp-deep-learning-parity.md) — inline-TikZ
  book; #98 #3 tikz-bail restores 88/88 figures off the held R13 pin

## Re-running parity tests

Parity tests run against `fixtures/book-dp1/`, `fixtures/book-dp2/`, and
`fixtures/book-dp-deep-learning/` — gitignored local clones of the upstream
book repos (on their `mystmd-conversion` branch) so the pipeline never
touches an in-progress branch in the sibling repos. Populate them first:

```bash
bash scripts/setup_fixtures.sh                 # bootstrap all three
bash scripts/setup_fixtures.sh --refresh dp1   # re-clone just dp1
```

Override the upstream locations with `BOOK_DP1_SRC=/path` /
`BOOK_DP2_SRC=/path` / `BOOK_DL_SRC=/path` if the sibling repos live elsewhere.

### Primary harness — `validate_fixture.sh` (two baselines)

The canonical parity check is `scripts/validate_fixture.sh`, which runs one
common regen → validate → diff process for any book against **two distinct
baselines** (see [`docs/design/`](../docs/design/) + CLAUDE.md):

```bash
bash scripts/validate_fixture.sh all                     # parity gap vs the
                                                          # worked-on mystmd/ (objective)
bash scripts/validate_fixture.sh all --against snapshot  # refactor-safety:
                                                          # regen must be byte-identical
                                                          # to the pinned _snapshot/ (gate)
bash scripts/validate_fixture.sh all --pin               # (re)pin the snapshot
bash scripts/validate_fixture.sh all --build           # + render gate: myst build
                                                          # vs tests/baselines/build-*.txt (lesson 046)
```

`--against snapshot` is the hard gate for a behavior-preserving change
(tool-vs-tool byte-identity, always achievable); the default `--against
baseline` is the parity *objective* to drive down (the worked-on `mystmd/`
carries irreducible hand-edits, so the bar is "close / only documented
drift"). The per-construct recipes below are still useful for a focused
regression check on one construct family.

### dp2 smoke test

Each book fixture has its own `regen/` directory carrying a working
`config.yaml`. Run the pipeline against that config and diff the
output against the committed `mystmd/` in the fixture.

```bash
bash scripts/convert.sh --config fixtures/book-dp2/regen/config.yaml
diff -r fixtures/book-dp2/mystmd/ fixtures/book-dp2/regen/ | head -20
```

Expected: cosmetic differences (YAML quoting style, line wrapping for
preface), plus any deliberate drift documented in the latest parity
report.

### dp1 algorithm-block parity (#014 regression check)

```bash
bash scripts/convert.sh --config fixtures/book-dp1/regen/config.yaml

# All chapters with algorithm2e blocks should produce byte-identical
# {prf:algorithm} directives to the upstream dp1 mystmd output.
for ch in ch_intro ch_mdps ch_rdps ch_state_dep ch_ctime; do
  awk '/^```{prf:algorithm}/{flag=1} flag{print} /^```$/ && flag{flag=0; print "==="}' \
    fixtures/book-dp1/mystmd/$ch.md > /tmp/dp1.txt
  awk '/^```{prf:algorithm}/{flag=1} flag{print} /^```$/ && flag{flag=0; print "==="}' \
    fixtures/book-dp1/regen/$ch.md > /tmp/ours.txt
  if diff -q /tmp/dp1.txt /tmp/ours.txt >/dev/null; then echo "$ch: ✓"; else echo "$ch: ✗"; fi
done
```

### dp1 listing parity (#015 regression check)

Same harness as the algorithm check, but grepping for `{code-block}`
fences instead of `{prf:algorithm}`. Affected chapters: `ch_intro`,
`ch_mcs`, `ch_mdps`, `ch_val`, `ch_ctime` (21 listings total).
