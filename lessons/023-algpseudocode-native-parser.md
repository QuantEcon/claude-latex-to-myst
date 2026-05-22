---
id: 023
title: "algpseudocode bodies need their own native parser — algorithm2e translation is lossy"
category: post-processing
tags: [algorithm, algpseudocode, algorithmicx, pseudocode, sentinel-markers]
source_project: Deep_Learning_for_Solving_And_Estimating_Dynamic_Economic_Models (external)
status: codified
codified_in: scripts/_apply_algorithmic_markers.py + scripts/postprocess.py::_algpseudo_convert_body + resolve_algorithmics
severity: medium
date: 2026-05-22
---

## Symptom

LaTeX books that use the `algorithmic` (algorithmicx / algpseudocode)
environment for pseudocode either had no support at all (raw `\STATE`,
`\FOR`, `\ENDFOR` markers leaking into the rendered markdown as
literal text inside a `::: algorithmic` div), or were unreachable
because the existing `\begin{algorithm}` preprocessor only knew the
algorithm2e dialect.

Two failing shapes:

1. **Standalone algorithmic in a custom wrapper.** E.g. inside
   `\begin{definitionbox}` (a project's tcolorbox), the inner
   `\begin{algorithmic}` was passed through pandoc unchanged and
   ended up as `::: algorithmic\n\STATE …\n\FOR{…} …\n:::`.
2. **`algorithmic` nested inside `\begin{algorithm}`.** The
   algorithm2e preprocessor base64-encoded the body verbatim, then
   `_algo_convert_body` ran the algorithm2e parser on it — which
   doesn't recognise `\STATE` / `\FOR` / `\ENDFOR` markers and left
   them as literal source.

## Why not translate to algorithm2e first?

Translation looks tempting (`\STATE x` → `x \;`, `\FOR{C} … \ENDFOR`
→ `\For{C}{…}`) and would reuse the existing `_algo_convert_body`.
But several algpseudocode constructs have no clean algorithm2e
equivalent:

- **`\REPEAT … \UNTIL{C}`.** algorithm2e's `\Repeat{body}` is
  one-arg — the condition is dropped. algpseudocode preserves it.
- **`\IF{C} body \ELSE body \ENDIF`.** algorithm2e's `\If{C}{body}`
  is body-arg only; there's a separate `\uIf` + `\Else` form, but
  the mapping is awkward and loses the natural mid-block `\ELSE`
  position.
- **`\LOOP … \ENDLOOP`.** No algorithm2e equivalent at all.
- **`\FORALL{C} … \ENDFOR`.** algorithm2e has `\ForEach{}{}` but it
  takes a body-arg, not a paired marker.
- **`\Comment{…}` annotations on lines.** algorithm2e has no line
  annotation primitive; the closest is a trailing `\tcp{…}` which
  wouldn't reuse the existing converter anyway.

Each translation gap would mean either silently dropping information
(losing the `\UNTIL` condition) or adding an algorithm2e extension
that the converter doesn't otherwise understand. The cost of a
native parser is roughly the same as building those extensions and
keeps both dialects independent.

## Fix

Sentinel-marker pattern (same shape as lessons 014, 015, 022) plus
a dialect-detecting dispatcher:

### 1. Standalone path: `_apply_algorithmic_markers.py`

Pre-pandoc preprocessor that finds `\begin{algorithmic}…\end{algorithmic}`
blocks not already consumed by `_apply_algorithm_markers.py` (which
runs first and base64-encodes any algorithmic block sitting inside
`\begin{algorithm}`). Emits:

```text
<!--ALGORITHMIC body=BASE64BODY-->
```

Base64-encoding ensures the algpseudocode commands survive pandoc
intact (pandoc otherwise reads `\STATE` etc. as unknown LaTeX macros
and may drop or reflow them). Pandoc preserves the HTML comment as
`\<!--…--\>`.

### 2. Native parser: `_algpseudo_convert_body`

A stack-based walker that tokenises on the algpseudocode keyword set
(`\STATE`, `\FOR{}`, `\ENDFOR`, `\WHILE{}`, `\ENDWHILE`, `\REPEAT`,
`\UNTIL{}`, `\IF{}`, `\ELSIF{}`, `\ELSE`, `\ENDIF`, `\LOOP`,
`\ENDLOOP`, `\FORALL{}`, `\REQUIRE`, `\ENSURE`, `\RETURN`,
`\COMMENT{}`, etc.) and emits Markdown bullets. Maintains a
`depth` counter and `stack` of open blocks so deeply-nested
structures indent correctly.

Key shapes:

| algpseudocode               | Markdown                       |
|-----------------------------|--------------------------------|
| `\STATE x`                  | `- x`                          |
| `\FOR{C} … \ENDFOR`         | `- for C:\n  - …`              |
| `\WHILE{C} … \ENDWHILE`     | `- while C:\n  - …`            |
| `\REPEAT … \UNTIL{C}`       | `- repeat:\n  - …\n- until C`  |
| `\IF{C} … \ELSE … \ENDIF`   | `- if C:\n  - …\n- else:\n  - …` |
| `\REQUIRE x` / `\ENSURE x`  | `- **Input:** x` / `**Output:** x` |
| `\RETURN x`                 | `- return x`                   |
| `\LOOP … \ENDLOOP`          | `- loop:\n  - …`               |

### 3. Dispatcher in `_algo_convert_body`

The algorithm-body converter (used by `resolve_algorithms` for
`\begin{algorithm}` wrappers) now detects algpseudocode keywords or
the `\begin{algorithmic}` wrapper at the top of the body and
delegates to `_algpseudo_convert_body`. A single `\begin{algorithm}`
block renders correctly whether the inner pseudocode is algorithm2e
or algorithmicx — the caller doesn't need to know.

### 4. Standalone decoder: `resolve_algorithmics`

Postprocess function that decodes the `<!--ALGORITHMIC body=…-->`
markers and calls `_algpseudo_convert_body`. No `{prf:algorithm}`
wrapper — there was no caption or label on the source, so the body
renders as bare bullets that fit inside whatever wrapper the author
chose (custom tcolorbox, `definitionbox` div, or plain prose).

## Scope decisions

- **Standalone `algorithmic` emits bare bullets, not a wrapped
  directive.** No caption or label to attach. The author's wrapper
  (whatever it is) provides the visual framing.
- **Line comments and size declarations (`\small`, `\footnotesize`,
  etc.) are stripped.** Authors use these for PDF rendering; no MyST
  analogue.
- **`\Comment{x}` inside a `\STATE` becomes `( -- x)` inline.**
  Preserves the annotation without needing a separate bullet.
- **Tolerant of mis-nested input.** `close_block` pops the stack
  until it finds the matching opener rather than asserting, so a
  source file with an `\ENDIF` before an `\ENDFOR` doesn't crash
  the converter.

## How to detect

```bash
# Pre-fix: ::: algorithmic divs with raw markers in output.
grep -rE '^::: algorithmic|\\STATE|\\FOR\{|\\ENDFOR|\\ENDWHILE|\\ENDIF' mystmd/*.md

# Post-fix: bullet lists, no raw markers, no algorithmic divs.
grep -rE '^::: algorithmic' mystmd/*.md      # zero
grep -rE 'ALGORITHMIC(-START|-END)?' mystmd/*.md  # zero — no leaked markers
```

## Generalizable rule

When a LaTeX dialect has features that don't cleanly translate into
another dialect you already support, write a native parser rather
than a lossy translation layer. The cost is roughly the same and
the result is faithful to the source.

This is the second time the sentinel-marker pattern has been applied
to a "pandoc reads as unknown LaTeX and reflows / drops the body"
case (algorithm2e was the first); the third is description envs
(lesson [022](022-description-item-labels-silently-dropped.md)). For
keyword-heavy bodies, the workflow is now:

1. Preprocess: wrap the block in a base64 sentinel marker.
2. Postprocess: decode the marker, run a dialect-specific parser
   on the body.
3. Tokenise the body on keyword positions, not character-by-character
   — keywords are well-known, prose between them isn't.

Related: lesson [014](014-algorithm2e-resolution.md) (algorithm2e),
lesson [022](022-description-item-labels-silently-dropped.md)
(description envs), lesson [008](008-pipeline-ordering.md)
(transform order).
