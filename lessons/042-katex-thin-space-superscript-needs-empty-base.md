---
id: 042
title: "KaTeX errors on `\\,^X` (superscript right after thin space) — insert an empty base `\\,{}^X`"
category: katex
tags: [katex, math, spacing, superscript, mystmd]
source_project: book-dp-deep-learning (ch11_climate, Round 5)
status: codified
codified_in: scripts/transforms/math.py::fix_spacing_superscript
severity: medium
date: 2026-05-28
---

## Symptom

KaTeX errors (build completes but the affected expressions render
broken) on any inline-math expression of the shape
``$<n>\,^\<sym>\mathrm{<unit>}$`` — most commonly degrees Celsius:

```
⛔️ ch11_climate.md:246 Got group of unknown type: 'internal'
   T_{\mathrm{AT}}=3\,^\circ\mathrm{C}
```

Surfaced in book-dp-deep-learning's R5 pass — 8 instances in the
climate chapter (``2.5\,^\circ\mathrm{C}``, ``3\,^\circ\mathrm{C}``,
etc.). Pre-existing, not refactor-induced.

## Cause

The LaTeX source ``\,^\circ`` is valid: ``\,`` is a thin space (a math
spacing macro emitting an "internal" mkern node), and ``^\circ`` is a
superscript attaching to the *implicit empty base* in front of it. LaTeX
honours that.

KaTeX does not. It tries to attach ``^`` to the immediately preceding
atom — which is the ``\,`` spacing node, type ``"internal"`` — and
bails with ``Got group of unknown type: 'internal'``. The same break
hits **every** superscript right after a thin space, not just
``^\circ``: ``\,^*``, ``\,^\dagger``, ``\,^\top``, ``\,^{2}``, etc.

## Fix

Insert an **explicit empty group** between the thin space and the
superscript — ``\,{}^X`` — so the superscript has a real (empty) base
to attach to. Visually identical, semantically transparent. Idempotent:
``\,{}^`` no longer contains ``\,^`` so re-running is a no-op.

In ``scripts/transforms/math.py::fix_spacing_superscript``:

```python
def fix_spacing_superscript(text: str) -> str:
    return re.sub(r'\\,\^', r'\\,{}^', text)
```

Wired in ``process_text`` **after all marker decoders**
(``resolve_table_markers``, ``resolve_exercise_markers``,
``resolve_listings``, ``resolve_algorithms``, ``resolve_algorithmics``).
Several preprocessors — most notably ``_apply_table_markers.py`` and the
algorithm/description ones — base64-encode their body content into
HTML-comment markers pre-pandoc, so any math inside is invisible to a
text-level regex until the matching decoder runs. An earlier-position
call would miss table cells (#85), algorithm bodies, etc. — the original
PR #84 made exactly that mistake.

Fenced *code* blocks and inline code spans are stashed/restored around
the rewrite so a tutorial passage displaying the literal ``\,^`` as an
example isn't silently mangled. The fenced-code regex skips MyST
**directive** fences (``\`\`\`{table}``, ``\`\`\`{exercise}``, …) via a
``(?!\{)`` lookahead — those are the very bodies we need to reach.

### What does NOT work

The original #45 wrote: "``\,\!^\circ`` (``\!`` adds a negative thin
space; sometimes parses where ``\,^`` doesn't)." **Verified against
myst 1.9.1 KaTeX: still errors.** Only the empty-base group works.
Don't ship the ``\!`` workaround.

The other plausible alternatives:
- ``\,°\mathrm{C}`` (Unicode degree) — works but changes the source
  character and only covers ``^\circ``, not ``^*`` / ``^\dagger`` / etc.
- ``^\circ\mathrm{C}`` (drop the thin space) — works but changes
  spacing visually.

The empty-base group is the only rewrite that's both fully general
(any superscript after ``\,``) and visually transparent.

## How to detect

A myst build that exits 0 can still have these — they're warnings, not
errors. Grep the build log:

```bash
myst build --html 2>&1 | grep -E "unknown type:\s*'internal'"
```

Each hit is one of these. After the fix lands, the count should be 0
for any input that previously triggered them.

## Generalizable rule

KaTeX is stricter than LaTeX about *what* a postfix operator can attach
to. Where LaTeX silently uses an implicit empty base, KaTeX often
demands an explicit one. The same ``{}`` empty-group escape hatch is
the canonical idiom — see also LaTeX's own ``{}^{prescript}`` form. If
``\;^``, ``\:^``, ``\!^`` ever surface as breaking too (same "internal"
node, same parser path), the same ``{}`` insertion will fix them; the
regex can be broadened to ``\\[,;:!]\^`` at that point.
