---
id: 010
title: "Don't rely on system Python — adopt uv so the pipeline manages its own interpreter"
category: tooling
tags: [python, uv, pep-668, setup]
source_project: claude-latex-to-myst (parity test against book-dp2)
status: codified
codified_in: pyproject.toml, scripts/convert.sh::bootstrap, scripts/preprocess.sh::bootstrap
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
by default. The goal is to prevent users from breaking OS-managed Python by
co-mingling dependencies.

The pipeline needs `pyyaml` (for config parsing). Without a managed venv,
the pipeline can't start — and asking users to set one up manually is
friction every new project will hit.

## Fix

Make `uv` the single source of truth. `pyproject.toml` declares
`requires-python = ">=3.10"` and `dependencies = ["pyyaml>=6.0"]`. The
lockfile (`uv.lock`) is committed for reproducible installs.

The shell scripts auto-bootstrap on every invocation:

```bash
if ! command -v uv &>/dev/null; then
  echo "ERROR: 'uv' required..." >&2
  exit 1
fi
(cd "$PROJECT_DIR" && uv sync --quiet)
export PATH="$PROJECT_DIR/.venv/bin:$PATH"
```

`uv sync` is a no-op when already in sync, so this costs ~50ms on warm
runs and ~3s on the first call. Users don't need to:
- Install Python (uv downloads the interpreter)
- Create a venv
- Activate anything
- Run `pip install`
- Set `PATH=...` themselves

The pipeline becomes truly one-command for new users.

## How to detect

The smoke test: delete `.venv/`, then run `bash scripts/convert.sh
--config example.yaml`. The script must:
1. Notice the venv is missing
2. Run `uv sync` to create it
3. Complete successfully

If any of those fails, the bootstrap is broken.

## Why uv over alternatives

- **`venv` + `requirements.txt`:** User has to install Python first
  (PEP 668 makes this gnarly on macOS/Ubuntu), create the venv, install
  deps, prefix `PATH`. Five steps where uv is one.
- **PEP 723 inline script metadata (`# /// script`):** Works for single
  scripts but our pipeline has shell scripts that call `python3` and
  helpers that `import` each other. Doesn't fit.
- **conda:** Heavier; many users don't have it; less idiomatic for tool
  repos.
- **Stdlib-only YAML parser:** ~50 lines of code we'd have to maintain
  to save one ~150KB dependency. Not worth it.
