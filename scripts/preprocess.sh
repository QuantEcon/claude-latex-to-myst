#!/bin/bash
# =============================================================================
# preprocess.sh — Sanitize LaTeX sources before pandoc
# =============================================================================
#
# Reads chapter list and rewrite rules from config.yaml. Writes preprocessed
# copies to {tmp_dir}/ — never modifies the originals.
#
# Usage:
#   preprocess.sh --config path/to/config.yaml
# =============================================================================

set -euo pipefail

# Portable in-place sed (BSD vs GNU)
sedi() {
  if [[ "$OSTYPE" == darwin* ]]; then
    sed -i '' "$@"
  else
    sed -i "$@"
  fi
}

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

# Bootstrap: ensure uv-managed venv is on PATH (no-op if already set up).
if ! command -v uv &>/dev/null; then
  echo "ERROR: 'uv' required. Install: curl -LsSf https://astral.sh/uv/install.sh | sh" >&2
  exit 1
fi
(cd "$PROJECT_DIR" && uv sync --quiet)
export PATH="$PROJECT_DIR/.venv/bin:$PATH"

CONFIG=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --config) CONFIG="$2"; shift 2 ;;
    --help|-h)
      echo "Usage: preprocess.sh --config path/to/config.yaml"
      exit 0
      ;;
    *) echo "Unknown arg: $1" >&2; exit 1 ;;
  esac
done

[[ -z "$CONFIG" ]] && { echo "ERROR: --config required" >&2; exit 1; }
[[ ! -f "$CONFIG" ]] && { echo "ERROR: config not found: $CONFIG" >&2; exit 1; }

CONFIG_DIR="$(cd "$(dirname "$CONFIG")" && pwd)"
SOURCE_DIR="$CONFIG_DIR/$(python3 "$SCRIPT_DIR/_config.py" "$CONFIG" source_dir)"
TMP_DIR="$CONFIG_DIR/$(python3 "$SCRIPT_DIR/_config.py" "$CONFIG" tmp_dir)"

SOURCE_DIR="$(cd "$SOURCE_DIR" && pwd)"

rm -rf "$TMP_DIR"
mkdir -p "$TMP_DIR"

# Read chapter stems (chapters + extra_files)
CHAPTER_STEMS=()
while IFS= read -r line; do
  [[ -n "$line" ]] && CHAPTER_STEMS+=("$line")
done < <(python3 "$SCRIPT_DIR/_config.py" "$CONFIG" chapters.stem)

while IFS= read -r line; do
  [[ -n "$line" ]] && CHAPTER_STEMS+=("$line")
done < <(python3 "$SCRIPT_DIR/_config.py" "$CONFIG" extra_files.stem)

# Stage 0: carve any consolidated multi-chapter .tex files (e.g. dp1's
# appendix.tex) into per-chapter pieces before per-stem preprocessing.
# Outputs land in TMP_DIR with the stem names listed under
# `preprocess.split.into`; the chapter loop below picks them up.
python3 "$SCRIPT_DIR/_apply_chapter_splits.py" "$CONFIG" "$SOURCE_DIR" "$TMP_DIR"

for ch in "${CHAPTER_STEMS[@]}"; do
  src="$SOURCE_DIR/${ch}.tex"
  dst="$TMP_DIR/${ch}.tex"

  # If the stem was produced by a chapter split (above), tmp/{stem}.tex
  # already exists — keep that content and skip the cp from source_dir.
  if [[ ! -f "$dst" ]]; then
    if [[ ! -f "$src" ]]; then
      echo "  WARN: $src not found, skipping" >&2
      continue
    fi
    cp "$src" "$dst"
  fi

  # All sed-style transforms (strip + rewrites + perl) run in Python — avoids
  # BSD vs GNU sed portability traps and shell quoting hell.
  python3 "$SCRIPT_DIR/_apply_rewrites.py" "$CONFIG" "$dst"

  # Replace \begin{algorithm}...\end{algorithm} (algorithm2e) with marker
  # comments. Pandoc would otherwise destroy the body structure. The
  # postprocess step decodes the markers into {prf:algorithm} directives.
  # No-op for sources that contain no algorithm blocks.
  python3 "$SCRIPT_DIR/_apply_algorithm_markers.py" "$dst"

  # Replace \begin{listing}...\end{listing} (minted) with marker comments.
  # The postprocess step reads the referenced source file and emits a MyST
  # code-block directive with :name: and :caption:. No-op for sources
  # that contain no listing blocks.
  python3 "$SCRIPT_DIR/_apply_listing_markers.py" "$dst"

  # Replace \begin{description}...\end{description} with DESCITEM markers.
  # Pandoc otherwise drops every \item[Term] label silently, leaving a
  # paragraph soup of definitions with no terms attached. The postprocess
  # step decodes the markers into MyST definition-list syntax. No-op for
  # sources that contain no description envs (GH #19).
  python3 "$SCRIPT_DIR/_apply_description_markers.py" "$dst"

  echo "  Preprocessed: ${ch}.tex"
done

echo ""
echo "Wrote preprocessed sources to: $TMP_DIR"
echo "Total: ${#CHAPTER_STEMS[@]} files"
