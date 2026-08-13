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
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

# Bootstrap: ensure uv-managed venv exists and is on PATH. uv sync is
# idempotent and fast (no-op if already in sync), so this is safe to call
# on every invocation.
if ! command -v uv &>/dev/null; then
  echo "ERROR: 'uv' required. Install: curl -LsSf https://astral.sh/uv/install.sh | sh" >&2
  exit 1
fi
(cd "$PROJECT_DIR" && uv sync --quiet)
export PATH="$PROJECT_DIR/.venv/bin:$PATH"

CONFIG=""
SINGLE_CHAPTERS=()
RUN_BUILD=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --config) CONFIG="$2"; shift 2 ;;
    --build)  RUN_BUILD=1; shift ;;
    --help|-h)
      cat <<'USAGE'
Usage: convert.sh --config CONFIG [--build] [CHAPTER_STEM...]

  --config CONFIG    Required. Path to the per-project config.yaml.
  --build            Optionally run `myst build --html` after the pipeline
                     and summarize errors/warnings. Skipped by default to
                     keep the iteration loop fast.

If CHAPTER_STEM args are given, only those chapters are processed.
USAGE
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

# Determine which chapters to process. Entries marked ``regen: false``
# are skipped — they're curated outside the regen flow and convert.sh
# must not overwrite them (#63). Stems and regen flags are pulled as
# parallel lists (blank lines preserved so indices stay aligned).
# bash 3.2 (macOS default) — no namerefs, so the filter is inlined.
ALL_STEMS=()
SKIPPED_STEMS=()

CH_STEMS=()
while IFS= read -r line; do CH_STEMS+=("$line"); done \
  < <(python3 "$SCRIPT_DIR/_config.py" "$CONFIG" chapters.stem)
CH_REGEN=()
while IFS= read -r line; do CH_REGEN+=("$line"); done \
  < <(python3 "$SCRIPT_DIR/_config.py" "$CONFIG" chapters.regen)

for i in "${!CH_STEMS[@]}"; do
  stem="${CH_STEMS[$i]}"
  regen="${CH_REGEN[$i]:-}"
  [[ -n "$stem" ]] || continue
  if [[ "$regen" == "False" ]]; then
    SKIPPED_STEMS+=("$stem")
    continue
  fi
  ALL_STEMS+=("$stem")
done

EF_STEMS=()
while IFS= read -r line; do EF_STEMS+=("$line"); done \
  < <(python3 "$SCRIPT_DIR/_config.py" "$CONFIG" extra_files.stem)
EF_REGEN=()
while IFS= read -r line; do EF_REGEN+=("$line"); done \
  < <(python3 "$SCRIPT_DIR/_config.py" "$CONFIG" extra_files.regen)

for i in "${!EF_STEMS[@]}"; do
  stem="${EF_STEMS[$i]}"
  regen="${EF_REGEN[$i]:-}"
  [[ -n "$stem" ]] || continue
  if [[ "$regen" == "False" ]]; then
    SKIPPED_STEMS+=("$stem")
    continue
  fi
  ALL_STEMS+=("$stem")
done

if [[ ${#SINGLE_CHAPTERS[@]} -gt 0 ]]; then
  # When the user names specific chapters, honour the request — even
  # ``regen: false`` stems can be force-converted this way (the gate is
  # for the default whole-book run).
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
if [[ ${#SKIPPED_STEMS[@]} -gt 0 && ${#SINGLE_CHAPTERS[@]} -eq 0 ]]; then
  echo "  Skipped (regen: false): ${SKIPPED_STEMS[*]}"
fi
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
# Stage 4: Copy figures (reference-aware, #154)
# ---------------------------------------------------------------------------
# Copies only the assets the generated .md actually references — a blanket
# copy of figures_dir diverges whenever postprocess.rewrites retarget
# includes to a different format (book-dp1's deleted source PDFs were
# re-copied on every run). Scan/copy logic lives in _copy_figures.py.
FIG_DIR_REL="$(python3 "$SCRIPT_DIR/_config.py" "$CONFIG" figures_dir || true)"
if [[ -n "${FIG_DIR_REL:-}" && "$FIG_DIR_REL" != "None" ]]; then
  echo "Stage 4: Copying figures..."
  python3 "$SCRIPT_DIR/_copy_figures.py" "$CONFIG"
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

# ---------------------------------------------------------------------------
# Stage 7 (opt-in): myst build smoke check
# ---------------------------------------------------------------------------
if [[ "$RUN_BUILD" -eq 1 ]]; then
  echo "Stage 7: myst build --html..."
  if ! command -v myst &>/dev/null; then
    echo "  WARN: 'myst' not on PATH; skipping. This pipeline needs the" >&2
    echo "        QuantEcon fork (github.com/QuantEcon/mystmd) at qe-v9 or" >&2
    echo "        later. Older builds render fine but number a multi-row" >&2
    echo "        align as ONE equation, so numbering drifts from the source." >&2
  else
    BUILD_LOG="$OUTPUT_DIR/_build.log"
    (cd "$OUTPUT_DIR" && myst build --html 2>&1) > "$BUILD_LOG" || true
    # Guard each grep with || true so set -e doesn't fire on "no matches".
    BUILD_ERRORS=$(grep -cE '⛔' "$BUILD_LOG" 2>/dev/null || true)
    BUILD_WARNS=$(grep -cE '⚠'  "$BUILD_LOG" 2>/dev/null || true)
    BUILD_ERRORS=${BUILD_ERRORS:-0}
    BUILD_WARNS=${BUILD_WARNS:-0}
    echo "  Totals: errors=$BUILD_ERRORS  warnings=$BUILD_WARNS"
    if [[ "$BUILD_ERRORS" -gt 0 || "$BUILD_WARNS" -gt 0 ]]; then
      echo "  First 5 issues:"
      grep -E '⛔|⚠' "$BUILD_LOG" | head -5 | sed 's/^/    /' || true
      echo "  To categorize all of them:"
      echo "    grep -oE 'Unhandled[^\"]*\"[a-z_]+\"|xref_not_found|duplicate_id|math_parse' $BUILD_LOG | sort | uniq -c | sort -rn"
    fi
    echo "  Full log: $BUILD_LOG"
  fi
  echo ""
fi

echo "=============================================="
echo " Done."
echo "=============================================="
if [[ "$RUN_BUILD" -ne 1 ]]; then
  echo "  Build site:    cd $OUTPUT_DIR && myst build --html"
fi
echo "  Preview:       cd $OUTPUT_DIR && myst start"
