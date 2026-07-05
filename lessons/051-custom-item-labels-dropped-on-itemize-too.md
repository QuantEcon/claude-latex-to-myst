---
id: 051
title: "Pandoc drops \\item[label] optional args on itemize too, not just enumerate/description — flatten any fully-labelled list to labelled paragraphs"
category: preprocess
tags: [itemize, enumerate, custom-item-labels, pandoc, silent-data-loss, list-flatten]
source_project: book-dp1 (§8.3.2.1, via QuantEcon/book-dp-public#34)
status: codified
codified_in: scripts/_apply_custom_label_enumerates.py (generalised opener/closer regexes from #111 to also pair itemize)
severity: medium
date: 2026-07-06
---

## Symptom

An `itemize` whose **every** `\item` carries an explicit `[label]`
rendered as plain bullets in MyST — the author-chosen `(a)`–`(d)`
markers vanished. In book-dp1 §8.3.2.1 this dropped the markers from a
list of assumptions and orphaned the prose immediately after it
("Condition (a) is…", "Conditions (b) and (c)…", "Condition (d)…"),
which no longer had anything to point at.

```latex
\begin{itemize}
    \item[(a)] the reward function is bounded and continuous
    \item[(b)] the discount factor satisfies $\beta \in (0,1)$
    \item[(c)] the transition kernel is Feller
    \item[(d)] the constraint correspondence is compact-valued
\end{itemize}
```

## Cause

The #111 custom-label flattener (`_apply_custom_label_enumerates.py`)
already handled this shape for `enumerate` — pandoc silently drops the
optional arg of `\item[(a)]` and renumbers the list `1..N`, so the fix
rewrites a *fully* custom-labelled list into blank-line-separated
labelled paragraphs pre-pandoc. But its outer opener/closer regexes
matched only `\begin{enumerate}` / `\end{enumerate}`. An `itemize` with
the identical every-item-has-`[…]` shape fell through to pandoc, whose
reader drops the optional arg exactly the same way, leaving a bullet
list. This is the same lossy-pandoc class as lesson
[022](022-description-item-labels-silently-dropped.md) (`description`
term labels) — the third list environment that discards `\item[…]`.

## Fix

Nothing in the *predicate* or the *output* was enumerate-specific — a
fully, manually labelled list is not an auto-counter (enumerate) or
bullet (itemize) list regardless of which env opened it, and the
faithful MyST is labelled paragraphs either way. Only the outer pairing
regexes needed generalising to match `enumerate` **and** `itemize`:

```python
_LIST_OPEN_RE  = re.compile(r'\\begin\{(?:enumerate|itemize)\}(?:\[[^\]]*\])?')
_LIST_CLOSE_RE = re.compile(r'\\end\{(?:enumerate|itemize)\}')
```

Pairing stays **by pure depth** (any list open `++`, any list close
`--`): LaTeX envs are properly nested/balanced, so name-matching is
unnecessary to find the outermost block, and a genuinely nested list
still bails via `_NEST_RE` inside `parse_custom_label_items`. All the
existing conservative bails carry over unchanged — an item without a
`[label]` (real bullet/counter list), a nested list env, real content
before the first `\item`, or an unclosed `[`.

Golden case: `tests/golden_tex/custom_label_itemize/`.

## How to detect

```bash
# A fully custom-labelled itemize that leaked to pandoc renders as
# bullets with the labels gone. In the source:
grep -nE '\\item\[' book/*.tex   # every \item in the block has [..]?

# Post-fix the block should be labelled paragraphs, not "- " bullets,
# and the prose references ("Condition (a)") should resolve visually.
```

## Generalizable rule

Pandoc drops the `\item[label]` optional argument on **every** list
environment — `enumerate`, `itemize`, and `description` — before the
markdown writer runs, so no post-pandoc regex can recover the labels.
When a construct's flatten/predicate is genuinely env-agnostic (as the
custom-label case is), generalise the *opener/closer* recognition
rather than duplicating the parser: pair the outer environments by
depth and let the body parser's existing bails do the safety work.

Related: lesson [022](022-description-item-labels-silently-dropped.md)
(description term labels), lesson
[008](008-pipeline-ordering.md) (transform order).
