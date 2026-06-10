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

# Read chapter stems (chapters + extra_files). Entries marked
# ``regen: false`` are skipped — they're curated outside the regen
# flow and convert.sh must not overwrite them (#63). Stems and regen
# flags are pulled as parallel lists (blank lines preserved so indices
# stay aligned). bash 3.2 (macOS default) — no namerefs.
CHAPTER_STEMS=()
SKIPPED_STEMS=()

# Inlined twice (once for chapters, once for extra_files) — namerefs would
# fold this into a helper but they're bash 4.3+; macOS still ships 3.2.

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
  CHAPTER_STEMS+=("$stem")
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
  CHAPTER_STEMS+=("$stem")
done

if [[ ${#SKIPPED_STEMS[@]} -gt 0 ]]; then
  for stem in "${SKIPPED_STEMS[@]}"; do
    echo "  Skipped (regen: false): ${stem}"
  done
fi

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

  # Preserve the optional [title] of theorem-family environments. Pandoc
  # drops the optional arg of a \begin{theorem}[Title] it can't resolve (and
  # renders \begin{proof}[Proof of …] inline, duplicating the auto heading),
  # so move the title into a PRFTITLE marker the postprocess env pass lifts
  # onto the {prf:*} directive argument. No-op for envs without a [title]
  # (#112).
  python3 "$SCRIPT_DIR/_apply_prf_title_markers.py" "$CONFIG" "$dst"

  # Replace \begin{algorithm}...\end{algorithm} (algorithm2e) with marker
  # comments. Pandoc would otherwise destroy the body structure. The
  # postprocess step decodes the markers into {prf:algorithm} directives.
  # No-op for sources that contain no algorithm blocks.
  python3 "$SCRIPT_DIR/_apply_algorithm_markers.py" "$dst"

  # Replace standalone \begin{algorithmic}...\end{algorithmic} (algorithmicx
  # / algpseudocode) with marker comments. The algorithm-marker pass above
  # already base64-encoded any algorithmic block wrapped inside
  # \begin{algorithm}, so this pass picks up only the standalone ones
  # (e.g. inside a custom tcolorbox wrapper). The postprocess step decodes
  # the markers into Markdown bullet lists. No-op for sources without
  # algorithmic blocks (GH #20).
  python3 "$SCRIPT_DIR/_apply_algorithmic_markers.py" "$dst"

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

  # Flatten enumerates whose every \item carries an explicit [label]
  # into labelled paragraphs (GH #111). Pandoc drops custom \item[(a)]
  # labels silently, renumbering the list 1..N — dp1's norm properties
  # render "1.-8." against the PDF's "(a)-(d)". No-op for sources
  # without the shape.
  python3 "$SCRIPT_DIR/_apply_custom_label_enumerates.py" "$dst"

  # Replace \begin{enumerate} blocks whose every \item carries
  # \label{ex:...} with EXERCISE marker pairs. Pandoc's enumerate
  # parser discards interior \label{} calls, so every exercise label
  # vanishes by the time the markdown is produced — back-references
  # from a solutions appendix (typically {prf:ref}`ex-chN-M`) then
  # dangle. The postprocess step decodes the markers into
  # {exercise} directives. No-op for enumerates that aren't
  # fully-labelled-exercise lists (GH #69).
  python3 "$SCRIPT_DIR/_apply_enumerate_markers.py" "$dst"

  # Replace \begin{table}...\end{table} (LaTeX float) with TABLE marker
  # comments. Pandoc's LaTeX reader collapses ALL interior \hline/\midrule
  # separators in simple_tables format — the LaTeX-side header row
  # identity is lost before pandoc produces output. This pre-pandoc
  # extraction preserves the structure. The postprocess step emits MyST
  # {table} directives. No-op for sources without \begin{table} floats
  # (#51, Path C from PR #41 R3).
  python3 "$SCRIPT_DIR/_apply_table_markers.py" "$dst"

  # Replace \begin{figure}...\end{figure} (LaTeX float) with FIGURE marker
  # comments — Phase 1 of the figure-handling architecture (closes
  # #89/#90/#92/#93). Pandoc's HTML emission for figures loses content:
  # empty <span class="citation"> spans drop cite keys, [[CITEP:X]] markers
  # leak unescaped inside <figcaption>, minipage / bare-{\footnotesize}
  # sub-captions get dropped. This pre-pandoc extraction batch-converts
  # the caption + sub-captions through pandoc (escaping brackets so
  # decode_natbib_markers can find them) and stores the structure in the
  # marker. The postprocess step (resolve_figure_markers) emits MyST
  # {figure} directives. Phase 1 bails on blocks containing
  # \begin{subfigure}; convert_html_figures handles those as before
  # (Phase 2 — issue #94).
  python3 "$SCRIPT_DIR/_apply_figure_markers.py" "$dst"

  echo "  Preprocessed: ${ch}.tex"
done

# Warn about custom text macros pandoc will silently drop (GH #22).
# Scans the source preamble(s) for \DeclareUrlCommand / \newcommand
# text-formatting macros, counts usages across the chapters, and
# prints a single warning with a suggested config.yaml rewrite block.
# Non-fatal — never blocks the pipeline. No-op when no such macros
# exist or none are used.
CHAPTER_PATHS=()
for ch in "${CHAPTER_STEMS[@]}"; do
  if [[ -f "$TMP_DIR/${ch}.tex" ]]; then
    CHAPTER_PATHS+=("$TMP_DIR/${ch}.tex")
  fi
done
if [[ ${#CHAPTER_PATHS[@]} -gt 0 ]]; then
  python3 "$SCRIPT_DIR/_warn_dropped_text_macros.py" \
    "$SOURCE_DIR" "${CHAPTER_PATHS[@]}" || true
fi

echo ""
echo "Wrote preprocessed sources to: $TMP_DIR"
echo "Total: ${#CHAPTER_STEMS[@]} files"
