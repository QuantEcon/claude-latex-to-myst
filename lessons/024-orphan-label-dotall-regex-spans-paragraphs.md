---
id: 024
title: "Orphan \\label{} + DOTALL catch-all spans paragraphs and swallows figures between equations"
category: regex-safety
tags: [equations, labels, regex, dotall, figures, swallow]
source_project: external book (Deep_Learning_for_Solving_And_Estimating_Dynamic_Economic_Models)
status: codified
codified_in: scripts/postprocess.py::convert_equations
severity: high
date: 2026-05-24
---

## Symptom

After conversion, fenced directives that sit between two display-math
equations in the source go missing from the final MyST build — even
though they survive into the converted `.md` file. The figures (or
`{prf:remark}` blocks, etc.) get silently consumed into the body of a
huge `$$\n…\n$$ (eq-foo)` math block, which MyST then renders as
malformed content.

In the book that surfaced this, 15 figures across 5 chapters were
dropped. Only visible during HTML build review (the markdown still
*looked* fine at the file level), which is the worst possible stage to
catch a converter bug.

## Cause

`convert_equations` had a three-step shape for labelled equations:

1. **Step 1** required `\label{}` *immediately after* `\begin{equation}`:

   ```python
   r'\$\$\\begin\{equation\}\s*\\label\{([^}]+)\}\s*(.*?)\\end\{equation\}\$\$'
   ```

   But the dominant LaTeX convention is `\begin{equation} body
   \label{eq:foo} \end{equation}` — body first, label after. Step 1
   silently skipped these.

2. **Step 3** caught the unlabeled form and emitted
   `$$\n{body}\n$$` — but with `\label{eq:foo}` now stranded *inside*
   the math body.

3. **Standalone-label cleanup regex** was supposed to handle the
   stranded labels:

   ```python
   re.sub(r'\$\$(.*?)\\label\{([^}]+)\}(.*?)\$\$',
          ..., flags=re.DOTALL)
   ```

   With `DOTALL` and `(.*?)`, the regex engine picks the nearest `$$`
   *before* the orphan label and the nearest `$$` *after*. The
   "nearest before" can easily be an inline `$$math$$` from a paragraph
   60+ lines back. Everything in between — including any `{figure}`,
   `{prf:remark}`, prose, etc. — is swallowed into one fused math
   block.

A single match in one chapter was measured at **8,127 characters** —
regression formula + intervening prose + five `<figure>` placeholders
+ two whole sections + the MSE equation, all collapsed into one
malformed `$$ … $$ (eq-mse)` block.

## Fix

Two complementary changes:

1. **Extract the label inside the equation-env pass.** Collapse the
   labelled/unlabelled passes into one that accepts `\label{}`
   anywhere inside the body. No orphan `\label{}` survives into the
   document body, so the catch-all can't mismatch against it:

   ```python
   def replace_equation(m):
       body = m.group(1).strip()
       lbl = re.search(r'\\label\{([^}]+)\}', body)
       if lbl:
           body = (body[:lbl.start()] + body[lbl.end():]).strip()
           return f'$$\n{body}\n$$ ({convert_label_colons(lbl.group(1))})'
       return f'$$\n{body}\n$$'

   text = re.sub(
       r'\$\$\\begin\{equation\*?\}\s*(.*?)\\end\{equation\*?\}\$\$',
       replace_equation, text, flags=re.DOTALL,
   )
   ```

2. **Bound the standalone-label cleanup to a single line.** Even with
   (1), some other equation env not yet special-cased could leak an
   orphan `\label{}`. Drop `DOTALL` and switch `(.*?)` to `[^\n]*?` so
   the match can't span paragraph breaks:

   ```python
   text = re.sub(
       r'\$\$([^\n]*?)\\label\{([^}]+)\}([^\n]*?)\$\$',  # no DOTALL
       lambda m: f'$$\n{(m.group(1) + m.group(3)).strip()}\n$$ '
                 f'({convert_label_colons(m.group(2))})',
       text,
   )
   ```

   The legitimate single-line case `$$math\label{eq:foo}$$` still
   matches; multi-line cases are now handled upstream in the env pass.

Tests: `test_convert_equations_label_after_body_in_equation_env` and
`test_convert_equations_standalone_label_does_not_cross_paragraphs`
([tests/test_transforms.py](../tests/test_transforms.py)).

## How to detect

Before fix, count standalone-label match spans:

```python
import re
text = open('post-pandoc-output.md').read()
for m in re.finditer(r'\$\$(.*?)\\label\{([^}]+)\}(.*?)\$\$',
                     text, flags=re.DOTALL):
    span = m.end() - m.start()
    if span > 500:  # any legitimate single-equation match is much smaller
        start = text[:m.start()].count('\n') + 1
        print(f'line {start}: label={m.group(2)!r}, span={span} chars')
```

A span > a few hundred chars means the regex is crossing paragraph
boundaries.

After fix, the same scan should produce no matches > ~200 chars in
typical equation-heavy chapters.

## Generalizable rule

**`DOTALL` + `(.*?)` is a footgun for any pattern that pairs
delimiters.** The non-greedy quantifier picks the nearest match in
both directions, but "nearest" is computed across the *entire* string
in `DOTALL` mode. Whenever a delimiter pair has a legitimate inline
form (here `$$x$$`) and a block form (here `$$ … $$` with newlines),
the catch-all regex will happily pair an inline opener with a block
closer pages later if any intervening token (here `\label{}`) appears
between them.

Defensive patterns:

- **Bound the match to one line** when the legitimate use case is
  single-line: `[^\n]*?` instead of `(.*?)` and drop `DOTALL`.
- **Extract structure earlier** so the catch-all sees less ambiguous
  input. Here, pulling `\label{}` out at the env-conversion stage
  means the catch-all never has to handle the orphan case at all.
- **Audit catch-all regex matches by span size** as part of pipeline
  development. Any DOTALL match whose span dwarfs the median is
  almost certainly crossing a boundary it shouldn't.
