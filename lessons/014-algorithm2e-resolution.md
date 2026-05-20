---
id: 014
title: "algorithm2e bodies need a custom parser — pandoc destroys their structure"
category: post-processing
tags: [algorithms, algorithm2e, pandoc, gap]
source_project: book-dp1 (parity test, gap identified)
status: open
codified_in: TODO — see book-dp1/mystmd/scripts/postprocess.py for reference implementation
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

## Why this is "open" not "codified"

Porting requires either:
- Rewriting the Perl preprocessor in Python (per lesson #009 — keep all
  regex work in Python), OR
- Adding a Perl dependency to the tool (regression on lesson #009)

Plus the 130-line algorithm-body parser. Estimated 3–4 hours of careful
work. Not yet done because:
- algorithm2e is common but not universal (dp2 doesn't use it)
- The current behavior is a clear, easy-to-diagnose failure rather than a
  silent corruption — users can see immediately that algorithm blocks need
  manual fixing
- Better to ship the simpler transforms first and add this when the next
  book actually needs it

## How to detect

```bash
grep -A 5 '```{prf:algorithm}' mystmd/ch_*.md | grep -v '^--$' | head -30
```

If the body is one flat paragraph instead of a bullet list, the algorithm
body wasn't reconstructed.

## Reference implementation

- `book-dp1/mystmd/scripts/_rewrite_algorithms.pl` (70 lines, Perl)
- `book-dp1/mystmd/scripts/postprocess.py::_algo_convert_body` (~130 lines)
- `book-dp1/mystmd/scripts/postprocess.py::resolve_algorithms` (~40 lines)
