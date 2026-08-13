---
id: 056
title: "Splitting math rows on `\\\\` with a flat regex shreds nested structures — the scan must track BOTH environment depth and brace depth, and the `&` / punctuation cleaners must be depth- and escape-aware too"
category: regex-safety
tags: [math, align, split-path, nesting, substack, intertext, katex, depth-scan]
source_project: claude-latex-to-myst (internal hardening; shapes latent across dp1/dp2/deep-learning)
status: codified
codified_in: scripts/transforms/math.py::_scan_top_level / _split_math_rows / _neutralize_top_level_amps / _renderable / _extract_intertext
severity: high
date: 2026-08-13
---

## Symptom

The per-row align splitter cut on every `\\` with one flat regex, and cleaned
each row with two more context-free regexes. Six distinct defects fell out —
all latent in the current books, but all reachable by ordinary LaTeX:

| shape | what happened |
|---|---|
| `\begin{cases} a \\ b \end{cases}` in a row | cut in half; unbalanced delimiters, hard KaTeX error |
| `\begin{bmatrix} 1 & 2 \\ 3 & 4 \end{bmatrix}` | as above, **plus** the matrix's own `&` eaten by the row's `&`→space rule |
| a row holding only `\label{}` | emptiness tested *before* stripping, so it survived as `$$\n\n$$ (eq-q)` — mystmd "No input for math node", and it consumed a number |
| a row ending `\,` | `[,;]\s*$` ate the comma of the thin space, leaving a bare trailing `\` — hard KaTeX error |
| `\\*` | unmatched, so a stray `*` prefixed the next row — **renders without error** |
| `\intertext{…}` | fused into the equation: hard KaTeX error, prose lost |

## Root cause

`\\` is only a row terminator at the *top level* of the body. A regex cannot
know that. The same is true of `&`: it separates the row's own columns only at
top level; inside a nested `bmatrix` it belongs to the matrix.

This is the regex-pairing failure mode lesson 042 established for fenced
blocks, in a different guise — and the repo's answer is the same: **one
left-to-right scan carrying explicit state**, never a pattern that tries to
infer structure it cannot see.

## Fix

`_scan_top_level` walks the body once, yielding `('rowbreak'|'amp', start,
end)` for depth-0 tokens only, and everything else is built on it.

## The four things that are easy to get wrong

**1. Environment depth alone is not enough — track brace depth too.**
`\substack{i=1 \\ j=2}`, `\text{a \\ b}`, `\mbox`, `\parbox` are *macros with
brace groups*, not environments, so a `\begin`/`\end` counter never sees them
and still shreds the row. `\substack` is **live in the deep-learning
fixture** (7 occurrences), unlike every other shape in this lesson — it only
escapes the bug today because it sits in a `\[…\]` that never reaches the
split path. Conversely brace depth alone is not enough either: the braces of
`\begin{cases}` balance *before* the inner `\\`. Both counters, split only
when both are zero.

**2. `%` comments must be skipped by the scan.** Pandoc passes them through
into math bodies verbatim. Without comment handling the depth scan acquires a
failure the flat regex never had: a commented-out `\begin{cases}` or a stray
`{` inside a comment poisons the counter permanently and suppresses *every*
later row break, silently collapsing the whole align into one row.

**3. Do not make the optional-length or star tolerant of whitespace.** TeX's
`\@ifstar` does skip spaces, so matching `\\ *` and `\\ [2ex]` looks more
correct — but `x \\ * is a product` and `x \\ [0,1] \ni y` are real content,
and absorbing them **deletes** it. Leaking a stray `*` is visible and
non-fatal; silently eating a row's opening token is not. Bind both only when
adjacent.

**4. Clamp the depth counters at zero.** An unbalanced `\end{}` otherwise
drives the count negative, suppressing every later row break and collapsing
the body — which then routes several labels into one block and trips the
label-replacement hazard.

## Deliberate non-goal

LaTeX *numbers* an empty row (a bare `\\`, an amp-only row, a trailing `\\`
before `\end{align}`), and this fix does **not** reproduce that: rows that
carry nothing referenceable are dropped. The justification for keeping
label-bearing empty rows is *"a dropped label dangles every reference to
it"*, not numbering fidelity — do not restate it as the latter, because the
two disagree. Chasing exact row-number parity is also moot while a multi-row
`align` still collapses to a single enumerator (#186 / QuantEcon/mystmd#73).
Zero of 234 real row-numbering bodies across the three books carry a trailing
`\\`, so nothing is lost in practice.

## Verification worth repeating

Every book's converted output is **byte-identical** before and after this
change — the correct signature for hardening a latent path. The most
dangerous of the six is the nested-`&` one, because it is the only one that
produces **no** error signal: a 2×2 `bmatrix` silently renders as 2×1, with a
clean build log. Check `columnalign` in the built MathML, not the console.

## Related

- Lesson 042 — the fence-stack precedent: state machine, never regex pairing.
- Lesson 055 / #192 — the other half of this splitter's rework.
- #186 — the remaining numbering gap, upstream.
