#!/bin/bash
# =============================================================================
# convert.sh — Master LaTeX → MyST Markdown Conversion Pipeline
# =============================================================================
#
# Orchestrates the full conversion driven by a project config.yaml.
#
# Pipeline stages:
#   1. Pre-process LaTeX     (preprocess.sh, writes tmp/*.tex)
#   2. Pandoc conversion     (latex → markdown)
#   3. Post-process Markdown (postprocess.py)
#   4. Copy figures          (source/figures → output/figures)
#   5. Copy bibliography     (source/.bib → output/references.bib)
#   6. Validate output       (validate.py)
#
# Usage:
#   convert.sh --config path/to/config.yaml [CHAPTER_STEM ...]
#
# If chapter stems are passed, only those chapters are converted. Otherwise
# every chapter in the config is processed.
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
CONFIG=""
SINGLE_CHAPTERS=()

while [[ $# -gt 0 ]]; do
  case "$1" in
    --config) CONFIG="$2"; shift 2 ;;
    --help|-h)
      echo "Usage: convert.sh --config CONFIG [CHAPTER_STEM...]"
      exit 0
      ;;
    *) SINGLE_CHAPTERS+=("$1"); shift ;;
  esac
done

[[ -z "$CONFIG" ]] && { echo "ERROR: --config required" >&2; exit 1; }
[[ ! -f "$CONFIG" ]] && { echo "ERROR: config not found: $CONFIG" >&2; exit 1; }

CONFIG="$(cd "$(dirname "$CONFIG")" && pwd)/$(basename "$CONFIG")"
CONFIG_DIR="$(dirname "$CONFIG")"
SOURCE_DIR="$(cd "$CONFIG_DIR/$(python3 "$SCRIPT_DIR/_config.py" "$CONFIG" source_dir)" && pwd)"
OUTPUT_DIR="$(cd "$CONFIG_DIR/$(python3 "$SCRIPT_DIR/_config.py" "$CONFIG" output_dir)" && pwd)"
TMP_DIR="$CONFIG_DIR/$(python3 "$SCRIPT_DIR/_config.py" "$CONFIG" tmp_dir)"

# Determine which chapters to process
ALL_STEMS=()
while IFS= read -r line; do
  [[ -n "$line" ]] && ALL_STEMS+=("$line")
done < <(python3 "$SCRIPT_DIR/_config.py" "$CONFIG" chapters.stem)
while IFS= read -r line; do
  [[ -n "$line" ]] && ALL_STEMS+=("$line")
done < <(python3 "$SCRIPT_DIR/_config.py" "$CONFIG" extra_files.stem)

if [[ ${#SINGLE_CHAPTERS[@]} -gt 0 ]]; then
  STEMS=("${SINGLE_CHAPTERS[@]}")
else
  STEMS=("${ALL_STEMS[@]}")
fi

echo "=============================================="
echo " LaTeX → MyST Conversion Pipeline"
echo "=============================================="
echo "  Config:   $CONFIG"
echo "  Source:   $SOURCE_DIR"
echo "  Output:   $OUTPUT_DIR"
echo "  Chapters: ${#STEMS[@]}"
echo ""

# ---------------------------------------------------------------------------
# Stage 1: Pre-process LaTeX
# ---------------------------------------------------------------------------
echo "Stage 1: Pre-processing LaTeX..."
bash "$SCRIPT_DIR/preprocess.sh" --config "$CONFIG"
echo ""

# ---------------------------------------------------------------------------
# Stage 2: Pandoc conversion
# ---------------------------------------------------------------------------
echo "Stage 2: Running pandoc..."
for ch in "${STEMS[@]}"; do
  src="$TMP_DIR/${ch}.tex"
  dst="$OUTPUT_DIR/${ch}.md"
  if [[ ! -f "$src" ]]; then
    echo "  WARN: $src missing, skipping"
    continue
  fi
  pandoc "$src" -f latex -t markdown --wrap=none -o "$dst"
  echo "  Converted: $ch"
done
echo ""

# ---------------------------------------------------------------------------
# Stage 3: Post-process Markdown
# ---------------------------------------------------------------------------
echo "Stage 3: Post-processing Markdown..."
if [[ ${#SINGLE_CHAPTERS[@]} -gt 0 ]]; then
  INPUTS=()
  for ch in "${SINGLE_CHAPTERS[@]}"; do
    INPUTS+=("$OUTPUT_DIR/${ch}.md")
  done
  python3 "$SCRIPT_DIR/postprocess.py" --config "$CONFIG" "${INPUTS[@]}"
else
  python3 "$SCRIPT_DIR/postprocess.py" --config "$CONFIG"
fi
echo ""

# ---------------------------------------------------------------------------
# Stage 4: Copy figures
# ---------------------------------------------------------------------------
FIG_DIR_REL="$(python3 "$SCRIPT_DIR/_config.py" "$CONFIG" figures_dir || true)"
if [[ -n "${FIG_DIR_REL:-}" && "$FIG_DIR_REL" != "None" ]]; then
  echo "Stage 4: Copying figures..."
  SRC_FIGS="$SOURCE_DIR/$FIG_DIR_REL"
  DST_FIGS="$OUTPUT_DIR/figures"
  mkdir -p "$DST_FIGS"
  if [[ -d "$SRC_FIGS" ]]; then
    count=0
    for ext in pdf png jpg jpeg svg; do
      for f in "$SRC_FIGS"/*."$ext"; do
        [[ -f "$f" ]] || continue
        dest="$DST_FIGS/$(basename "$f")"
        if [[ ! -f "$dest" ]] || [[ "$f" -nt "$dest" ]]; then
          cp "$f" "$dest"
          count=$((count + 1))
        fi
      done
    done
    echo "  Copied/updated $count figures"
  else
    echo "  WARN: $SRC_FIGS not found"
  fi
  echo ""
fi

# ---------------------------------------------------------------------------
# Stage 5: Copy bibliography
# ---------------------------------------------------------------------------
BIB="$(python3 "$SCRIPT_DIR/_config.py" "$CONFIG" bibliography || true)"
if [[ -n "${BIB:-}" && "$BIB" != "None" ]]; then
  echo "Stage 5: Copying bibliography..."
  SRC_BIB="$SOURCE_DIR/$BIB"
  DST_BIB="$OUTPUT_DIR/references.bib"
  if [[ -f "$SRC_BIB" ]]; then
    if [[ ! -f "$DST_BIB" || "$SRC_BIB" -nt "$DST_BIB" ]]; then
      cp "$SRC_BIB" "$DST_BIB"
      echo "  Updated references.bib"
    else
      echo "  references.bib up to date"
    fi
  else
    echo "  WARN: $SRC_BIB not found"
  fi
  echo ""
fi

# ---------------------------------------------------------------------------
# Stage 6: Validate
# ---------------------------------------------------------------------------
echo "Stage 6: Validating..."
python3 "$SCRIPT_DIR/validate.py" --config "$CONFIG" || true
echo ""

echo "=============================================="
echo " Done."
echo "=============================================="
echo "  Build site:    cd $OUTPUT_DIR && myst build --html"
echo "  Preview:       cd $OUTPUT_DIR && myst start"
