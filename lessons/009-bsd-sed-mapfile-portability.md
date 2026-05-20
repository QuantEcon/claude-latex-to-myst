---
id: 009
title: "BSD sed and bash 3.2 break the preprocess pipeline on macOS"
category: tooling
tags: [macos, bash, sed, portability]
source_project: claude-latex-to-myst (parity test against book-dp2)
status: codified
codified_in: scripts/_apply_rewrites.py
severity: medium
date: 2026-05-20
---

## Symptom

On macOS, the initial `preprocess.sh` failed with two distinct errors:

1. `preprocess.sh: line 61: mapfile: command not found`
2. `sed: 1: "s/\\index\{[^}]*\}//g": RE error: invalid repetition count(s)`

## Cause

Two separate portability traps on macOS's default tooling:

1. **`mapfile` is bash 4+.** macOS ships bash 3.2 (the last GPL-2 release).
   Any script that uses `mapfile -t arr < <(...)` won't run on a default
   macOS install.

2. **BSD sed treats `\{` and `\}` as bounded-repetition syntax**, not as
   literal braces. So `s/\\index\{[^}]*\}//g` parses as "literal backslash,
   then `index`, then *broken* repetition." GNU sed accepts both
   interpretations.

## Fix

For (1): use a `while IFS= read -r line; do ...; done < <(...)` loop, which
works on bash 3.2+.

For (2): the bigger lesson is that shell + sed is a portability minefield
for non-trivial regex work. Move all sed-style rewrites into Python via
`re.sub`. Python's regex semantics are consistent across platforms, and the
config file no longer has to know which sed dialect the user has.

The pipeline now does *all* LaTeX preprocessing in Python
(`scripts/_apply_rewrites.py`); `preprocess.sh` is now just a thin
chapter-iteration wrapper.

## How to detect

Run the pipeline on a fresh macOS machine with no GNU coreutils installed.
If the smoke test passes there, BSD-vs-GNU traps are gone.

## General rule

Any non-trivial regex work in a portable shell pipeline should live in
Python (or another runtime with consistent regex semantics), not in
`sed`/`awk`/`grep -P`. The "POSIX-compatible sed" you write almost never is.
