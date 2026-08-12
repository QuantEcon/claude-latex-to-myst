---
id: 017
title: "Pandoc class attributes leak into MyST labels — capture only the first whitespace-delimited token"
category: regex-safety
tags: [pandoc, frontmatter, labels, unnumbered, attribute-block]
source_project: book-dp2 (common_symbols regen)
status: codified
codified_in: scripts/postprocess.py::convert_section_labels
severity: high
date: 2026-05-20
---

## Symptom

After regenerating `common_symbols.md` for dp2, the frontmatter contained a
malformed label:

```yaml
---
title: "Notation"
label: common-symbols-and-terminology .unnumbered
---

(c-cs)=
```

Two things wrong:
1. The label value contained a literal space and a dot-prefixed token
   (`.unnumbered`) — not a valid MyST identifier and not a slug pandoc
   ever intended as an id.
2. The author's explicit `\label{c:cs}` survived as an orphan body anchor
   `(c-cs)=` below the heading, with no link to the frontmatter label.

Filed as Issue 2 of [`FIX-frontmatter-and-tables.md`](../reports/2026-05-20-fix-frontmatter-and-tables.md).
Blocked dp2 from a clean `common_symbols.md` regen — every re-run reintroduced
the corruption.

## Cause

Pandoc renders an unnumbered chapter like:

```latex
\chapter*{Common Symbols and Terminology}
\addcontentsline{toc}{chapter}{Common Symbols}
\label{c:cs}
```

as a heading with **both** an auto-generated id and a class attribute:

```markdown
# Common Symbols and Terminology {#common-symbols-and-terminology .unnumbered}

[]{#c:cs label="c:cs"}
```

The `{#…}` block holds the heading's HTML attributes — `#slug` is the id,
and `.unnumbered` / `.unlisted` are *class* tokens, not part of the id.

`convert_section_labels` was matching with:

```python
r'^(#{1,6})\s+(.+?)\s+\{#([^}]+)\}\s*$'
```

The `[^}]+` greedily captured everything between `{#` and `}`, including
the trailing `.unnumbered`. The capture was then passed straight to
`convert_label_colons` (which only swaps `:` → `-`), so the class token
rode along into the emitted body anchor `(slug .unnumbered)=`. By the time
`add_frontmatter` ran, the heading auto-id had a literal space inside it,
which then got written to YAML as a broken `label:` value.

The same issue would affect any pandoc-emitted attribute block that
appends class tokens or key=value props — for example
`{#sec:foo .unlisted}` or `{#sec:foo class="extra"}`.

## Fix

Take only the first whitespace-delimited token from the captured attribute
block — that's the `#slug`. Discard anything that follows (classes,
properties).

```python
def replace_header(m):
    hashes = m.group(1)
    title = m.group(2).strip()
    slug = m.group(3).split()[0]
    label = convert_label_colons(slug)
    return f'({label})=\n{hashes} {title}'
```

The same defensive pattern applies anywhere a regex captures content
inside pandoc's `{…}` attribute blocks: a slug is one token; everything
else inside the braces is metadata that the slug never owned.

`convert_standalone_labels` is already safe — it uses `[^\s}]+` for the
id capture, which terminates at whitespace.

## How to detect

```bash
# Any frontmatter label containing a space or a dot — both are illegal
# in MyST identifiers and almost always indicate a class-leak.
grep -E '^label:.*[. ]' mystmd/*.md
```

Should return zero results on clean output. A post-fix re-run of dp2 returns
zero hits (committed dp2 has 1: the buggy `common_symbols.md`).

## Related

Pairs with lesson [018](018-greedy-explicit-label-promotion.md): once the
class-attribute leak was fixed, `add_frontmatter` still needed a second
guard to prefer the *explicit* `\label{}` body anchor over the heading
auto-id — and that guard had its own over-greedy bug.
