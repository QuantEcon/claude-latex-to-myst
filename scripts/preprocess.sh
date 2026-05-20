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

# Read strip patterns, simple rewrites, and perl scripts from config
mapfile -t STRIP_PATTERNS < <(python3 "$SCRIPT_DIR/_config.py" "$CONFIG" preprocess.strip)

for ch in "${CHAPTER_STEMS[@]}"; do
  src="$SOURCE_DIR/${ch}.tex"
  dst="$TMP_DIR/${ch}.tex"

  if [[ ! -f "$src" ]]; then
    echo "  WARN: $src not found, skipping" >&2
    continue
  fi

  cp "$src" "$dst"

  # 1. Strip patterns (each becomes `s/PATTERN//g`)
  for pat in "${STRIP_PATTERNS[@]}"; do
    [[ -z "$pat" ]] && continue
    sedi "s/${pat}//g" "$dst"
  done

  # 2. Custom rewrites (handled via a small Python helper for safety)
  python3 "$SCRIPT_DIR/_apply_rewrites.py" "$CONFIG" "$dst"

  echo "  Preprocessed: ${ch}.tex"
done

echo ""
echo "Wrote preprocessed sources to: $TMP_DIR"
echo "Total: ${#CHAPTER_STEMS[@]} files"
