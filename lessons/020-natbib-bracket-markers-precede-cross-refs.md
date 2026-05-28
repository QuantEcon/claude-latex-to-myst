---
id: 020
title: "Natbib variants pandoc can't distinguish need bracket-marker sentinels — and the decode pass must run before cross-refs"
category: post-processing
tags: [citations, natbib, pandoc, cross-references, regex-safety, lesson-002-cousin]
source_project: book-dp2 (preface citealp, ch_egs citeyearpar)
status: codified
codified_in: scripts/_apply_rewrites.py::_NATBIB_REWRITES + scripts/postprocess.py::decode_natbib_markers
severity: high
date: 2026-05-20
---

## Symptom

dp2's preface had `\citealp{stokey1989recursive,puterman2005markov,
hernandez2012discrete}` (which natbib renders as "Author Year") but the
pipeline emitted `{cite}`-style parenthetical form. ch_egs had
`\citeyearpar{bellman1957dynamic}` (year-with-parens) which came out
as broken `[-{cite:t}\`bellman1957dynamic\`]` — neither `{cite:year}`
nor parenthesized.

Filed as Issue 3 of [`FIX-frontmatter-and-tables.md`](../FIX-frontmatter-and-tables.md).

After landing a preprocess rewrite layer to mark these variants with
`[[CITEP:keys]]` sentinels, a worse failure surfaced: some
`\citep{epstein1989risk, weil1990nonexpected}` calls *vanished* from
the output entirely. The whole `[[CITEP:…]]` marker was being eaten
along with surrounding paragraph text.

## Cause

Two coupled problems.

### 1. Pandoc collapses natbib variants ambiguously

Pandoc's LaTeX reader treats several natbib commands as synonyms:

| LaTeX                | Pandoc emits   | What we want      |
|----------------------|----------------|-------------------|
| `\cite{X}`           | `[@X]`         | `{cite}`          |
| `\citep{X}`          | `[@X]`         | `{cite:p}`        |
| `\citealp{X}`        | `[@X]`         | `{cite:t}` *      |
| `\citet{X}`          | `@X`           | `{cite:t}`        |
| `\citealt{X}`        | `@X`           | `{cite:t}`        |
| `\citeauthor{X}`     | `@X`           | `{cite:author}`   |
| `\citeyear{X}`       | `[-@X]`        | `{cite:year}`     |
| `\citeyearpar{X}`    | `[-@X]`        | `({cite:year})`   |

\* `\citealp` renders as "Author Year" (no parens). Closest MyST role is
`{cite:t}` per the FIX note's variant table.

Pandoc therefore cannot losslessly map all natbib variants — the
parenthetical-vs-no-paren and year-only distinctions are gone by the
time we post-process. Either preprocess (rewrite before pandoc), pandoc
filter (Lua), or both must intervene.

### 2. Bracket-marker sentinels collide with the cross-ref regex

Solution to #1: rewrite each ambiguous natbib variant in the .tex
source to a unique bracketed sentinel that pandoc passes through
verbatim::

    \citep{epstein1989risk, weil1990nonexpected}
        → [[CITEP:epstein1989risk, weil1990nonexpected]]

Pandoc preserves `[[…]]` as `\[\[…\]\]` (escapes the brackets but keeps
the content). Postprocess decodes back to `{cite:p}\`keys\``.

But: the leading `\[\[` looks like the start of a pandoc cross-reference
emission, which uses the shape::

    [display](#target){reference-type="eqref" reference="target"}

The existing `convert_cross_references` regex matches `[display](...)`
non-greedily on `]` but allows escaped `\]` in the display, and runs
across an entire `--wrap=none` paragraph. So given input::

    preferences \[\[CITEP:epstein1989risk, weil1990nonexpected\]\]
    play. Bellman equation [\[eq:osbell\]](#eq:osbell){reference-type="eqref"...}

the regex starts matching at the first `[` of the marker, treats the
escaped `\]` inside `\]\]` as a literal escape-allowed bracket, and
finally pairs with the EQUATION reference's `](#eq:osbell){…}` many
characters later — swallowing the marker entirely and emitting only
the `{eq}` ref.

This is the same shape as lesson [002](002-cross-ref-regex-eats-equations.md)
("Cross-ref regex consumes equation blocks via `[0,1)` bracket
false-match") — a regex designed to recognise pandoc's bracketed
constructs latches onto a different bracketed construct that came
along later.

## Fix

Two parts, both required.

### Preprocess: rewrite ambiguous variants to bracket-marker sentinels

In [`scripts/_apply_rewrites.py`](../scripts/_apply_rewrites.py), built-in
`_NATBIB_REWRITES` runs against the .tex file before pandoc::

    _NATBIB_REWRITES = [
        (r'\\citep\b\s*\{([^}]+)\}',       r'[[CITEP:\1]]'),
        (r'\\citealp\b\s*\{([^}]+)\}',     r'[[CITEALP:\1]]'),
        (r'\\citealt\b\s*\{([^}]+)\}',     r'[[CITEALT:\1]]'),
        (r'\\citeauthor\b\s*\{([^}]+)\}',  r'[[CITEAUTHOR:\1]]'),
        (r'\\citeyearpar\b\s*\{([^}]+)\}', r'[[CITEYEARPAR:\1]]'),  # before \citeyear
        (r'\\citeyear\b\s*\{([^}]+)\}',    r'[[CITEYEAR:\1]]'),
    ]

`\citeyearpar` must precede `\citeyear` because the shorter pattern
would otherwise win (`\citeyear` matches as a prefix of `\citeyearpar`).
The `\b` boundary protects against future false-matches if more
`\cite…` variants are added.

### Postprocess: decode markers BEFORE convert_cross_references

In [`scripts/postprocess.py`](../scripts/postprocess.py), the marker
decoder is its own function (`decode_natbib_markers`) wired into
`process_file` *before* `convert_cross_references`::

    text = convert_equations(text)
    text = decode_natbib_markers(text)       # ← MUST be before cross-refs
    text = convert_cross_references(text)
    ...
    text = convert_citations(text)           # pandoc-native [@key] / @key

Once the markers are decoded to `{cite:p}\`…\``, the leading `[` is gone
and the cross-ref regex can't latch onto them.

## How to detect

```bash
# 1. No undecoded markers should appear in final output.
grep -rE 'CITEP|CITEALP|CITEALT|CITEAUTHOR|CITEYEAR|CITEYEARPAR' mystmd/*.md

# 2. No stray pandoc suppress-author brackets [-@…].
grep -rE '\[-@' mystmd/*.md

# 3. Citation counts should match source counts (uncommented):
#    \cite ≈ {cite}, \citep ≈ {cite:p}, \citet+\citealt ≈ {cite:t},
#    \citeyearpar ≈ ({cite:year}).
```

All three return zero in dp2's regenerated output. Pre-fix, the third
was misaligned (14 source `\citep` → 11 `{cite:p}` because 3 were eaten
by cross-refs).

## Locator-arg gotcha (GH #13)

Natbib's optional `[locator]` args (`\citep[p.~351]{key}`,
`\citep[prenote][postnote]{key}`) break the rewrite if the pattern
forces `{` to follow the command name directly. Original pattern was::

    r'\\citep\b\s*\{([^}]+)\}'

— the `\s*\{` anchor lets a citation with a locator slip past
unchanged. Pandoc then renders `\citep[p.~351]{key}` as roughly
`[@key, p.~351]`, and the multi-cite regex in `convert_citations`
(`@(\S+?)(?:;|\])`) can't terminate inside that bracket group, so
`replace_multi_cite` finds zero keys and emits an empty `` {cite}`` ``
— silent data loss.

Fix: match up to two optional `[…]` groups between the command and the
`{key}`, and discard them. MyST's `{cite:*}` roles have no locator-
suffix syntax, so the locator can't be routed anywhere::

    _NATBIB_OPT = r'(?:\s*\[[^\]]*\]){0,2}'
    (rf'\\citep\b{_NATBIB_OPT}\s*\{{([^}}]+)\}}',  r'[[CITEP:\1]]'),
    # …same for the other 5

The detection grep at "How to detect" above won't surface this — the
output looks superficially valid (`` {cite}`` ``), just empty. The
better signal is a `grep -rE "\{cite[^}]*\}\`\`"` for empty-key roles.

### Follow-on: plain `\cite[loc]{key}` (GH #74)

The #13 fix was applied to the six rewritten variants but **not** to
plain `\cite` — deliberately, because `\cite{key}` (no locator) round-
trips correctly through pandoc's native path (`[@key]` → `{cite}`). But
`\cite[p.~351]{key}` hits the identical failure: pandoc emits
`[@key, p.~351]`, the key is lost, and an empty `` {cite}`` `` is
rendered. Found in book-dp2 (one site), silent past the validator.

Fix: add a `\cite` rule **gated on the presence of a locator**, so the
no-locator form stays on pandoc's path::

    _NATBIB_OPT_REQUIRED = r'\s*\[[^\]]*\](?:\s*\[[^\]]*\])?'  # ≥1 bracket
    (rf'\\cite\b{_NATBIB_OPT_REQUIRED}\s*\{{([^}}]+)\}}', r'[[CITE:\1]]'),

Two subtleties: (1) `\cite\b` will *not* match `\citep`/`\citet`/etc. —
there is no word boundary between `e` and the following letter — so the
existing variants are untouched. (2) In the decode alternation, `CITE`
is a prefix of `CITEP`/`CITEALP`/…, so it must be listed **last**
(`…|CITEYEARPAR|CITE`) and only `CITE:` (with the colon) reaches it.
`[[CITE:key]]` decodes to `{cite}` (no suffix), matching the plain path.

## Generalizable rule

When introducing a new sentinel that uses syntax similar to an existing
pandoc construct, audit every regex that matches that construct's shape
to be sure the sentinel doesn't get false-matched. The cost of one extra
pipeline stage (or one re-ordering of stages) is far less than the cost
of debugging citations that vanish without warning.

Related: lesson [002](002-cross-ref-regex-eats-equations.md) (the
original cross-ref regex / `[0,1)` bracket trap), lesson
[008](008-pipeline-ordering.md) (transform order is critical).
