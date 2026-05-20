---
id: 010
title: "PEP 668 blocks pip install on modern system Python — always document a venv"
category: tooling
tags: [python, pip, pep-668, setup]
source_project: claude-latex-to-myst (parity test against book-dp2)
status: codified
codified_in: README.md (quick start), requirements.txt
severity: low
date: 2026-05-20
---

## Symptom

A user trying to run the pipeline hits:

```
error: externally-managed-environment

× This environment is externally managed
╰─> ...you can override this, at the risk of breaking your Python installation
    or OS, by passing --break-system-packages.
```

…even on `pip install --user pyyaml`.

## Cause

PEP 668 (adopted by Homebrew Python, Debian/Ubuntu, and most distro-packaged
Pythons from 2023 onward) blocks `pip install` against the system interpreter
by default. The goal is to prevent users from accidentally breaking OS-managed
Python.

The script `from _config import load` relies on `yaml`, which isn't a stdlib
module — so without a managed venv the pipeline can't start.

## Fix

Document a venv-based setup as the *recommended* path in the README, not an
afterthought. Ship a `requirements.txt`. Don't suggest `pip install --user`
or `--break-system-packages` — both will fail or leak.

```bash
uv venv .venv --python 3.12
uv pip install --python .venv/bin/python -r requirements.txt
PATH="claude-latex-to-myst/.venv/bin:$PATH" bash scripts/convert.sh ...
```

The `PATH=...` prefix is the simplest way to make `python3` inside the
shell scripts resolve to the venv interpreter without forcing every shell
script to know about virtualenv activation.

## How to detect

Smoke test the README quick-start on a fresh macOS or Ubuntu install. If
step 1 (install pyyaml) requires `--break-system-packages`, your
instructions are out of date.

## Alternative considered

A stdlib-only YAML parser would eliminate the dependency entirely. Rejected
because (a) writing a robust YAML subset parser is more code than the rest
of `_config.py` combined, and (b) PyYAML is so universally available that
a one-line venv setup is the lesser evil.
