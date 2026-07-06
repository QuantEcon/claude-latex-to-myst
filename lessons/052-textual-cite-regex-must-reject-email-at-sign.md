---
id: 052
title: "Textual @key citation regex must reject an @ glued to a word char — else emails and URLs become bogus citations"
category: regex-safety
tags: [citation, email, mailto, url, pandoc, over-greedy-regex, cite]
source_project: Deep_Learning_for_Solving_And_Estimating_Dynamic_Economic_Models (external)
status: codified
codified_in: scripts/transforms/cite.py::convert_citations (widened the textual-@key lookbehind)
severity: medium
date: 2026-07-06
---

## Symptom

An email address in a `mailto:` link came out with a citation role
spliced into the middle of it:

```latex
\href{mailto:jane.doe@unil.ch}{\nolinkurl{jane.doe@unil.ch}}
```

rendered as

```markdown
[`jane.doe{cite:t}`unil`.ch`](mailto:jane.doe{cite:t}`unil`.ch)
```

— a broken address **and** an unresolvable `` {cite:t}`unil` `` that the
citation validator flags as a missing key. The same mangle hit the bare
`\href{mailto:…}{…}` autolink form and any `\url{…/user@host}`.

## Cause

**Not pandoc.** Pandoc's LaTeX reader treats `mailto:` URLs, `\nolinkurl`,
and `\url` bodies as verbatim/URL context and emits the `@` literally
inside the link/autolink/inline-code (verified on pandoc 3.8, the CI
pin). The misparse was entirely in our postprocess: `convert_citations`
converts pandoc's textual-citation form `@key` → `` {cite:t}`key` `` with

```python
r'(?<![`\[@])@([a-zA-Z][a-zA-Z0-9_:]*[a-zA-Z0-9_])(?=[^a-zA-Z0-9_]|$)'
```

The negative lookbehind rejected only a preceding `` ` ``, `[`, or `@` —
**not** a preceding word char. So in `jane.doe@unil.ch` the `@` is glued
to `e`, the lookbehind passes, and `@unil` is captured as a cite key. The
comment even *claimed* it "guards against email addresses"; it never did.

## Fix

Pandoc's own rule for distinguishing a `@key` citation from an email is
that the `@` must be preceded by a **boundary** (start of string,
whitespace, `(`, `[`), never by an alphanumeric. Widen the lookbehind to
reject a preceding word char and the email/URL local-part punctuation
that can sit right before the `@`:

```python
r'(?<![`\[@\w.+%/-])@([a-zA-Z][a-zA-Z0-9_:]*[a-zA-Z0-9_])(?=[^a-zA-Z0-9_]|$)'
```

`jane.doe@unil`, `.../user@host`, `foo@example.com` all have a local-part
char immediately before the `@` and are now left verbatim; a genuine
textual cite (`see @smith2020`, `@jones1999 shows`, `(@doe2001)`) is
preceded by a boundary and still converts. One-character-class change,
no new pass.

## How to detect

```bash
# A cite role wedged inside an address or URL is the signature.
grep -rnE '(mailto:|https?://)[^ )]*\{cite' mystmd/*.md   # zero after fix
grep -rnE '[[:alnum:].]@[[:alnum:]]' mystmd/*.md          # emails intact
```

The structural-count validator also surfaces it indirectly: the bogus
`` {cite:t}`unil` `` is an unresolvable citation key (P1a cross-ref
resolution).

## Generalizable rule

A regex that recognises a sigil-prefixed token (`@key`, `#tag`, `$math`)
in already-converted Markdown must anchor on the **left boundary**, not
just forbid a couple of adjacent characters. For `@`-citations the
correct boundary is "not glued to a word char / local-part punctuation" —
exactly pandoc's rule — because emails and URLs are the ambient
counter-examples. When a guard's comment claims it handles a case, add a
test that actually exercises that case (the pre-#179 test *locked the
buggy behaviour* as a "known imperfection", which is why it survived).

Related: lesson [031](031-textual-citation-regex-truncates-at-colon.md)
and lesson [035](035-citation-regex-trailing-colon-swallowed-into-key.md)
(other `@key` boundary bugs), lesson
[020](020-natbib-bracket-markers-precede-cross-refs.md) (citation
decoding order).
