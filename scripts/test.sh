#!/bin/bash
# =============================================================================
# test.sh — Run the pytest suite.
# =============================================================================
#
# Thin wrapper that auto-syncs the uv environment (including the dev
# group that pulls in pytest) and runs the suite under tests/.
#
# Usage:
#   bash scripts/test.sh                  # run everything
#   bash scripts/test.sh -k frontmatter   # filter by node-id substring
#   bash scripts/test.sh -v               # verbose
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

if ! command -v uv &>/dev/null; then
  echo "ERROR: 'uv' required. Install: curl -LsSf https://astral.sh/uv/install.sh | sh" >&2
  exit 1
fi
(cd "$PROJECT_DIR" && uv sync --quiet)

cd "$PROJECT_DIR"
# Coverage is informational only — no minimum enforced. Override with
# --no-cov for a faster run when iterating on a single test.
exec uv run --quiet pytest --cov=scripts --cov-report=term-missing:skip-covered "$@"
