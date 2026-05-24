---
id: 031
title: "Textual @key citation regex truncates at the first `:` — JabRef/Mendeley keys broken"
category: regex-safety
tags: [pandoc, citations, regex, natbib]
source_project: external book (Deep_Learning_for_Solving_And_Estimating_Dynamic_Economic_Models)
status: codified
codified_in: scripts/postprocess.py::convert_citations
severity: medium
date: 2026-05-25
---

## Symptom

A textual citation `\citet{Bertsekas:2000:DPO:517430}` round-trips
through pandoc as `@Bertsekas:2000:DPO:517430`, then
`convert_citations` rewrites only the prefix:

```
The canonical reference is {cite:t}`Bertsekas`:2000:DPO:517430.
```

`Bertsekas` alone is not a valid bib key, so MyST renders `[Bertsekas?]`
and the literal `:2000:DPO:517430` survives as plain text after the
citation role.

In the downstream Deep-Learning book: 5 sites across 3 chapters.

## Cause

The textual-citation regex at `convert_citations` had:

```python
r'(?<![`\[@])@([a-zA-Z][a-zA-Z0-9_]+(?:\d{4}[a-zA-Z]?)?)(?=[^a-zA-Z0-9_]|$)'
```

`[a-zA-Z0-9_]+` excludes `:`, so the capture stops at the first colon
in the key. Bracketed multi-cite (`[@key]`) uses a different regex
that allows non-word chars and so round-trips colon-bearing keys
correctly — only the textual `\citet{...}` (no brackets) form was
affected.

Colon-bearing keys are common in any project that imports from JabRef,
Mendeley, or older ACM/IEEE bibliographies — their auto-generated key
style is `Author:Year:Tag`.

## Fix

Add `:` to the allowed key char class **and** mirror it in the
boundary lookahead (so the key still ends at a word boundary):

```python
r'(?<![`\[@])@([a-zA-Z][a-zA-Z0-9_:]+(?:\d{4}[a-zA-Z]?)?)(?=[^a-zA-Z0-9_:]|$)'
```

Trace against `@Bertsekas:2000:DPO:517430.`:

- Greedy `[a-zA-Z0-9_:]+` consumes `ertsekas:2000:DPO:517430`.
- Trailing `.` is not in the key class; lookahead matches `[^a-zA-Z0-9_:]`.
- Capture: `Bertsekas:2000:DPO:517430`. Period stays as sentence
  punctuation.

Other shapes considered and rejected:

- **Adding `.` / `/` to the key class.** Both the issue proposal and
  some bibkey generators allow them, but they introduce ambiguity
  with sentence punctuation and URLs — none of the affected examples
  needed them. YAGNI.
- **Non-greedy `+?` with a positive boundary set.** Works but
  fragile: a stray bib-key with an unusual trailing char would not
  match. The negated-class boundary is more robust.

Tests in `tests/test_transforms.py`:
`test_citation_textual_colon_bearing_keys` (parametrized over 5 real
keys), `test_citation_textual_colon_key_at_end_of_sentence`,
`test_citation_textual_plain_key_trailing_period_unchanged`.

## How to detect

After a pipeline run, grep the produced MyST for the broken-cite
shape:

```bash
grep -nE '\{cite:t\}`[^`]+`:[A-Za-z0-9]' mystmd/*.md
```

Any hit means a colon-bearing key was truncated and the suffix leaked
into the rendered text. A clean run has zero hits.

## Generalizable rule

**Character classes in citation/cross-ref regexes must mirror what
the real-world key generators emit, not what looks "nice".** Pandoc
preserves whatever the bib key actually contains; the postprocess
regex is the only place the key shape is constrained. When in doubt,
list the affected keys from the failing book and extend the class to
cover exactly those characters — no more, no less.
