---
id: 014
title: "algorithm2e bodies need a custom parser — pandoc destroys their structure"
category: post-processing
tags: [algorithms, algorithm2e, pandoc]
source_project: book-dp1 (parity test, gap identified)
status: codified
codified_in: scripts/_apply_algorithm_markers.py + postprocess.py::resolve_algorithms
severity: high
date: 2026-05-20
---

## Symptom

Algorithm blocks from `algorithm2e` (the LaTeX package providing
`\KwIn`, `\While`, `\Repeat`, `\Return`, etc.) come out as a single
run-on paragraph after our pipeline:

```
```{prf:algorithm}

an initial state $X_0$ is given $t \leftarrow 0$ the controller of
the system observes the current **state** $X_t$ the controller chooses
an **action** $A_t$ the controller receives a **reward** $R_t$ that
depends on the current state and action the state updates to
$X_{t+1}$ $t \leftarrow t + 1$
```
```

Compare to dp1's properly-structured output:

```
```{prf:algorithm}
:label: algo-intro-auto-1

- an initial state $X_0$ is given
- $t \leftarrow 0$
- while $t < T$:
  - the controller of the system observes the current **state** $X_t$
  - the controller chooses an **action** $A_t$
  - ...
```
```

## Cause

Pandoc has no understanding of `algorithm2e`'s markup language. It flattens
`\While{cond}{body}` into prose, strips `\;` statement terminators, and
runs everything together. There's no way to recover the structure from the
pandoc output alone — the algorithm body must be intercepted *before*
pandoc sees it.

## Fix (gap — not yet codified)

The dp1 implementation is the reference. It works in three steps:

1. **Preprocess** (`_rewrite_algorithms.pl`): walks the .tex source, finds
   `\begin{algorithm}...\end{algorithm}` blocks, extracts the label/title
   from the `\caption`, base64-encodes the body, and emits an HTML-comment
   marker:

   ```html
   <!--ALGORITHM name=algo-foo title=Title body=BASE64BODY-->
   ```

   Base64 is necessary because the body contains `\;` and `\While` which
   pandoc would otherwise mangle.

2. **Pandoc** passes the HTML comment through verbatim.

3. **Postprocess** (`resolve_algorithms` + `_algo_convert_body`): finds the
   markers, decodes the body, and runs a recursive parser that knows
   `algorithm2e` control commands:
   - `\KwIn{x}` → `- input: x`
   - `\While{C}{B}` → `- while C:` with B indented
   - `\Repeat{B}` → `- repeat:` with B indented
   - `\;` → bullet boundary
   - `\If{C}{B}`, `\lIf{C}{B}`, `\For{C}{B}` etc.

   The parser is ~130 lines (`_algo_convert_body`) and uses balanced-brace
   matching (`_algo_find_balanced`).

## Codified implementation

Ported from dp1 in three pieces, all Python (no Perl, per lesson #009):

1. **`scripts/_apply_algorithm_markers.py`** — replaces the dp1 Perl
   preprocessor. Run inside `preprocess.sh` after `_apply_rewrites.py`,
   before pandoc. Walks the `.tex` source, extracts `\caption{\label{...} ...}`,
   base64-encodes the body, and emits one `<!--ALGORITHM name=... title=...
   body=BASE64-->` marker per algorithm. Blocks without a caption get an
   auto-generated label `algo-{chapter}-auto-{N}` so cross-refs still work.

2. **`postprocess.py::_algo_convert_body`** — ~130-line recursive parser
   for algorithm2e control commands (`\While`, `\For`, `\If`, `\uIf`,
   `\ElseIf`, `\lIf`, `\Repeat`, `\Return`, `\KwIn`, `\KwOut`, `\KwResult`).
   Uses balanced-brace matching (`_algo_find_balanced`) and a `\NEWLINE\`
   placeholder to track statement boundaries.

3. **`postprocess.py::resolve_algorithms`** — finds the markers in the
   post-pandoc text (tolerating pandoc's `\<...\>` escaping) and emits
   `{prf:algorithm}` directives. Wired into `process_file` between
   `convert_environment_divs` and `convert_equations`.

Verified byte-identical to dp1's committed output for ch_intro, ch_mdps,
ch_rdps, ch_state_dep, ch_ctime (the five chapters with algorithm2e blocks).

## Side bug fixed during port

The verification surfaced a regex bug in `convert_equations` independent
of algorithm2e support. Pandoc emits `$\Xsf$ $$` when an inline-math
closer abuts a display-math opener (LaTeX source: `$\Xsf$\n%\n\begin{equation*}`).
The "Ensure opening `$$` separated from preceding text" regex previously
used `([^\n$])\s+\$\$\n`, excluding `$` from the character class. This
caused the opener to stick to the prose line, MyST parsed it as inline
math, and the downstream blank-line state-machine got stuck `in_math`
for the rest of the file — stripping every subsequent blank line.

Fix: change to `([^\n])[ \t]+\$\$\n` (matches dp1; allows `$` before
whitespace, restricts to horizontal whitespace only).

## How to detect a regression

```bash
grep -A 5 '```{prf:algorithm}' mystmd/ch_*.md | grep -v '^--$' | head -30
```

If the body is one flat paragraph instead of a bullet list, the algorithm
body wasn't reconstructed.

## Reference implementation (historical)

- `book-dp1/mystmd/scripts/_rewrite_algorithms.pl` (70 lines, Perl) — replaced
- `book-dp1/mystmd/scripts/postprocess.py::_algo_convert_body` (~130 lines) — ported
- `book-dp1/mystmd/scripts/postprocess.py::resolve_algorithms` (~40 lines) — ported
