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

## Re-running parity tests

Parity tests run against `fixtures/book-dp1/` and `fixtures/book-dp2/` —
local copies of the upstream book repos so the conversion pipeline never
touches an in-progress branch in `../book-dp1` or `../book-dp2`. The
`fixtures/` directory is gitignored and must be populated before testing:

```bash
bash scripts/setup_fixtures.sh                 # bootstrap dp1 + dp2
bash scripts/setup_fixtures.sh --refresh dp1   # re-sync just dp1
```

Override the upstream locations with `BOOK_DP1_SRC=/path BOOK_DP2_SRC=/path`
if the sibling repos live elsewhere.

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
