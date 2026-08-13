---
id: 058
title: "Pandoc mints an auto-id for every heading and a starred sectioning command forces it into the output — promoting those derived slugs to `(slug)=` collides project-wide, so only promote a slug the author could have chosen"
category: post-processing
tags: [headings, anchors, labels, auto-identifiers, starred-sections, duplicate-id, frontmatter]
source_project: Deep_Learning_for_Solving_And_Estimating_Dynamic_Economic_Models (external)
status: codified
codified_in: scripts/transforms/frontmatter.py::_pandoc_auto_id + convert_section_labels
severity: medium
date: 2026-08-14
---

## Symptom

Every build of the deep-learning book printed two warnings:

```
⚠️  ch01_intro.md Duplicate identifier in project "further-reading"
⚠️  ch01_intro.md Duplicate identifier in project "exercises"
```

mystmd reports each collision once, so the pair badly understates it: the
anchor `(exercises)=` was emitted in **12** files and `(further-reading)=`
in **11**. `addTarget` registers the first occurrence and drops the rest, so
of the 12 "Exercises" sections only chapter 1's was a real project target —
and a later `[](#exercises)` written anywhere in the book would have
silently pointed at chapter 1.

## Cause

Two behaviours compose into the bug.

**Pandoc's `auto_identifiers` is on for `latex → markdown`,** so it derives
an id for every heading whether or not the author wrote a `\label{}`. It
normally *omits* the `{#id}` attribute block when it can re-derive that id
itself — which is why an unlabelled *numbered* `\section` leaks nothing.
But a **starred** command emits `.unnumbered`, and that forces an attribute
block which drags the derived id along:

```latex
\section*{Exercises}          →   ## Exercises {#exercises .unnumbered}
```

**`convert_section_labels` promoted every `{#…}` it saw.** An author-chosen
`\label{}` and a pandoc-derived slug arrive in exactly the same syntax, so
the transform could not tell them apart. Author labels are unique by
construction; derived slugs are only as unique as the section title.

dp1 and dp2 never showed it because both label essentially every sectioning
command. Deep-learning was the first book whose repeated section titles were
unlabelled — and they are unlabelled *precisely because* they are
`\section*`.

## Fix

Suppress the anchor when the slug is exactly what pandoc would have derived
from the heading title. That is the case where dropping it **costs
nothing**: mystmd's `headingLabelTransform` mints an *implicit* identifier
for an unlabelled heading and sets `node.identifier = normalized.html_id`,
i.e. the same string our anchor produced. Implicit headings are also exempt
from the duplicate-identifier check, which is what clears the warnings:

```ts
// packages/myst-transforms/src/enumerate.ts
if ((node as any).implicit) return; // Do not warn on implicit headings
```

So the identifier, the `html_id`, the in-page anchor and the first-wins
collision behaviour are all unchanged — only the warnings go.

Two things make the predicate safe, and both are load-bearing:

**Compare against the title, don't look up an author-label set.** The
obvious implementation is to scan the `.tex` sources for heading `\label{}`s
and promote only known ones. That is *fail-closed*: a scan miss (a `.tex`
outside a non-recursive glob, an `\input`, a custom sectioning macro,
`\part`/`\subparagraph`) silently drops a real anchor and dangles every
reference to it. Title-slug equality has no such mode — when the
reconstruction is imperfect the slug simply doesn't match, the anchor
survives, and behaviour reverts to the status quo. It also protects the
whole `sec:`/`ss:`/`c:` labelling convention for free: pandoc strips colons,
so a slug containing one can never equal a derived id. Measured over dp1,
dp2 and deep-learning the two predicates select **exactly the same 35
anchors**, so the safer one is free.

**Never suppress at depth 1.** `add_frontmatter` keys on the `(label)=` +
`# Title` pair. Remove an H1 anchor and, in `absorbed` style, the page loses
its `label:` (four deep-learning pages take their page target from an
unlabelled `\chapter*` H1); in `standalone` style it is worse — `heading_m`
goes `None`, the function synthesises a header from config and prepends it
to a body that still carries the bare H1:

```
standalone / anchor kept:       '(further-reading)=\n# Further Reading\n\nSome text.\n'
standalone / anchor SUPPRESSED: '# Further Reading\n\n# Further Reading\n\nSome text.\n'
```

The `absorbed` branch has a `bare_h1` guard for this; `standalone` does not.
H1 slugs are per-file chapter titles and don't collide anyway, so gating
depth 1 out costs nothing.

**Leave pandoc's within-file dedup suffixes alone.** A second same-titled
heading gets `{#optimality-1}`. Those are unique by construction, so they
never produce the warning — and suppressing one is *not* identifier-neutral,
because mystmd would mint `optimality`, a different string.

## Verification

Isolating the change (regen on the branch vs regen on `main`, not vs the
snapshot — the snapshots were stale and their noise would have masked it)
gives **exactly 3 / 8 / 24 anchor-line deletions and zero additions** across
dp1 / dp2 / deep-learning. Project-wide anchor sets shrink by exactly those
names, **0 cross-references newly dangle** in any book, and the two
deep-learning build warnings go to zero with no new warning.

## Generalisation

Any construct where pandoc emits author intent and derived metadata in the
*same* syntax needs a discriminator, and the discriminator should be chosen
so that guessing wrong is a no-op rather than a data loss. Here "does this
look like something the tool generated?" is strictly safer than "is this in
my list of things the author wrote?", because the first fails towards
keeping output and the second fails towards deleting it.

Related: [042](042-katex-thin-space-superscript-needs-empty-base.md) and
[056](056-math-row-splitting-must-be-depth-aware.md) on preferring a
structural test over a pattern list.
