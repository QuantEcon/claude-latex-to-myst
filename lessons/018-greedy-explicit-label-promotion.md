---
id: 018
title: "Promoting a body anchor to chapter label needs a non-heading guard — or it steals the first section's id"
category: post-processing
tags: [frontmatter, labels, section-anchors, regex-safety]
source_project: book-dp2 (ch_apps regression during Issue 2 fix)
status: codified
codified_in: scripts/postprocess.py::add_frontmatter
severity: high
date: 2026-05-20
---

## Symptom

While fixing lesson [017](017-pandoc-class-attrs-leak-into-labels.md)
(Issue 2 of [`FIX-frontmatter-and-tables.md`](../reports/2026-05-20-fix-frontmatter-and-tables.md)),
the first cut of "prefer the explicit `\label{}` body anchor over the
heading auto-id" caused a regression in `ch_apps.md`:

```yaml
# Source: \chapter{Additional Applications}\label{c:apps}
#         \section{Job Search}\label{s:optstop}

---
title: "Additional Applications"
label: s-optstop          # ← WRONG. Should be c-apps.
---
```

The chapter's frontmatter inherited the *first section's* label. dp2
cross-references like `{prf:ref}\`c-apps\`` would have stopped resolving,
and the section label `s-optstop` would have been duplicated (frontmatter
+ body anchor → MyST duplicate-id warning).

## Cause

The promotion logic for resolving the dual-anchor case
(`\chapter*{Title}` + separate `\label{}`) looked for the next
`(slug)=` body anchor after the heading and promoted its id to the
chapter's frontmatter label:

```python
heading_m = re.match(r'\(([^)]+)\)=\s*\n# (.+)\n', text)
if heading_m:
    rest = text[heading_m.end():].lstrip('\n')
    follow_m = re.match(r'\(([^)]+)\)=\s*(?:\n|$)', rest)
    if follow_m:
        following_anchor_label = follow_m.group(1)  # over-greedy
```

That works for `common_symbols.md`:

```markdown
(common-symbols-and-terminology)=
# Common Symbols and Terminology

(c-cs)=
**Mathematical Notation**       ← non-heading content → c-cs IS the chapter's
```

But it misfires for any chapter that opens with a section anchor:

```markdown
(c-apps)=
# Additional Applications

(s-optstop)=
## Job Search                   ← next line IS a heading → s-optstop is THAT section's
```

The next `(slug)=` after the chapter heading isn't always a chapter-level
explicit `\label{}`. It might be the section anchor for the very next
section. Whoever owns the line immediately *after* the anchor (heading vs.
content) is who owns the anchor.

This is a near-cousin of lesson [008](008-pipeline-ordering.md) (ordering)
and lesson [002](002-cross-ref-regex-eats-equations.md) (a regex eating
content it didn't intend to). The shape: "regex matches the *next* X,
where X is sometimes the X-you-want and sometimes the X-that-comes-after".

## Fix

Guard the promotion: only treat the body anchor as the chapter's if the
line immediately following the anchor is **not** a markdown heading.

```python
follow_m = re.match(r'\(([^)]+)\)=\s*\n(.*?)(?:\n|$)', rest)
if follow_m and not re.match(r'#{1,6}\s', follow_m.group(2)):
    following_anchor_label = follow_m.group(1)
```

The regex now captures the line after the anchor as `group(2)` and skips
the promotion when that line starts with `#{1,6}\s` (i.e. is itself a
heading).

This works because in MyST, a `(slug)=` anchor always labels what *follows*
it: a paragraph, a directive, a heading, etc. If what follows is a
section heading, the anchor is that section's id, not the chapter's.

## How to detect

```bash
# Look for frontmatter labels that match a section-style prefix
# (s-, ss-, sss-, sec-) where the file is a chapter — symptom of
# a section anchor being promoted to chapter-level by mistake.
for f in mystmd/ch_*.md mystmd/common_symbols.md mystmd/preface.md; do
  lbl=$(awk '/^---$/{c++; if(c==2) exit} c==1 && /^label:/' "$f")
  case "$lbl" in
    *"label: s-"*|*"label: ss-"*|*"label: sss-"*|*"label: sec-"*)
      echo "$f: $lbl"
      ;;
  esac
done
```

Should return zero results. Caught on the first re-run against the dp2
fixture during the Issue 2 fix.

## Generalizable rule

Any transform that "promotes" content from position N to position M
(frontmatter, attribute, label) must verify that position N's content
belongs to the same scope as position M. "Next thing after X" is rarely
the same as "thing that belongs to X". Add a guard on what follows the
candidate before promoting.
