---
id: 041
title: "A {list-table} nested in a {table} double-enumerates — suppress the inner with :enumerated: false"
category: myst
tags: [myst, tables, list-table, enumeration, numref, caption, mystmd]
source_project: book-dp-deep-learning (ch06_ha_youngs)
status: codified
codified_in: scripts/transforms/tables_from_latex.py::emit_myst, scripts/transforms/tables.py::convert_simple_tables
severity: medium
date: 2026-05-28
---

## Symptom

Table `{numref}` cross-references drift by one part-way through a
chapter — the rendered sequence skips a number (e.g. "Table 6.7",
"Table 6.9", no "Table 6.8"). The gap appears right after a captioned
table whose header row has an empty first cell (`& \textbf{A} & …`),
or any captioned table with 0 or 2+ header rows.

## Cause

A captioned table with exactly one header row is emitted as a `{table}`
wrapping a markdown **pipe-table** — the pipe-table is not a directive,
so mystmd sees one enumerable container. But 0-header and 2+-header
tables can't be a pipe-table (pipe-tables have exactly one header row,
and a 0-header one renders a visible synthetic empty row), so they fall
back to a `{list-table}` nested inside the `{table}`:

```md
````{table}
:name: tab-x

caption

```{list-table}
:header-rows: 0

* - …
```
````
```

mystmd counts **both** the outer `{table}` and the inner `{list-table}`
as enumerable `kind: table` containers. The inner one (unnamed) claims a
phantom `tab-N.M` slot, so every later table's number is off by one.

## Fix

Add `:enumerated: false` to the **nested** `{list-table}` — mystmd 1.9.1
honours it (the inner container then reports `enumerator=None`), so only
the outer `{table}` is numbered:

```md
```{list-table}
:header-rows: 0
:enumerated: false

* - …
```
```

Only suppress when nested: a *standalone* `{list-table}` (uncaptioned,
unwrapped) is itself the enumerable container and must keep its number.
Codified in `emit_myst` (marker path) and `convert_simple_tables`
(pandoc-output path).

### Why not just drop the wrapper and self-caption the list-table?

Tempting — a bare `{list-table} My caption` with `:name:` is a single
container, no phantom. **But** captions routinely contain inline-role
backticks (`{cite:t}`smith2023``, `{ref}`x``). On the directive
*argument* line those backticks break mystmd's argument parser and the
table **silently collapses** — the container vanishes from the AST and
the breakage cascades into following tables. (`:caption:` as an *option*
is rejected outright as "unexpected option".) The `{table}` wrapper
keeps the caption as a body paragraph, where roles parse normally — so
the wrapper stays; only the inner enumeration is suppressed.

## How to detect

Build the AST and count `kind: table` containers — a numbered container
with no label is a phantom:

```python
import json
def tables(n, out):
    if isinstance(n, dict):
        if n.get('type')=='container' and n.get('kind')=='table':
            out.append((n.get('enumerator'), n.get('label')))
        for v in n.values(): tables(v, out)
    elif isinstance(n, list):
        for v in n: tables(v, out)
    return out
# myst build --html, then load _build/site/content/<page>.json
out = tables(json.load(open('_build/site/content/ch06.json')), [])
phantom = [e for e,l in out if e is not None and not l]
assert not phantom, f"phantom enumerated container(s): {phantom}"
```

## Generalizable rule

Nesting two containers of the same `kind` (table-in-table,
figure-in-figure) makes mystmd enumerate both. When a wrapper exists
only to attach a caption/label to an inner directive, suppress the
inner's enumeration (`:enumerated: false`) so the pair counts once. See
also [019] / [025] for the table-parsing side of this family.
