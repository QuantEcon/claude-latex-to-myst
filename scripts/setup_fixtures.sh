#!/bin/bash
# =============================================================================
# setup_fixtures.sh — Populate fixtures/ with local copies of sibling book repos
# =============================================================================
#
# Creates fixtures/book-dp1/, fixtures/book-dp2/ and
# fixtures/book-dp-deep-learning/ by copying just the parts of each upstream
# repo needed to run the parity tests:
#   - the LaTeX sources we convert from
#   - the committed mystmd/ output (so we can diff against it)
#   - any TikZ overrides / scripts the test config references
#
# Why copies rather than symlinks: the user prefers fully-isolated copies so
# running the pipeline here never touches an in-progress branch in the
# upstream repos. fixtures/ is gitignored.
#
# Each fixture carries a regen/ config (separate output_dir) so a regen never
# clobbers the committed mystmd/ baseline that is the diff target.
#
# Usage:
#   scripts/setup_fixtures.sh                  # set up dp1, dp2 and deep-learning
#   scripts/setup_fixtures.sh dp1              # set up just dp1
#   scripts/setup_fixtures.sh dp2              # set up just dp2
#   scripts/setup_fixtures.sh deep-learning    # set up just the DL book
#   scripts/setup_fixtures.sh --refresh        # delete + rebuild
# =============================================================================

set -euo pipefail

# Portable in-place sed (BSD vs GNU) — same shim as preprocess.sh.
sedi() {
  if [[ "$OSTYPE" == darwin* ]]; then
    sed -i '' "$@"
  else
    sed -i "$@"
  fi
}

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
FIXTURES_DIR="$PROJECT_DIR/fixtures"

# Where to find the upstream repos. Override with env vars if your layout differs.
BOOK_DP1_SRC="${BOOK_DP1_SRC:-$PROJECT_DIR/../book-dp1}"
BOOK_DP2_SRC="${BOOK_DP2_SRC:-$PROJECT_DIR/../book-dp2}"
BOOK_DL_SRC="${BOOK_DL_SRC:-$PROJECT_DIR/../Deep_Learning_for_Solving_And_Estimating_Dynamic_Economic_Models}"

REFRESH=0
REGEN_ONLY=0
TARGETS=()

for arg in "$@"; do
  case "$arg" in
    --refresh) REFRESH=1 ;;
    --regen-only) REGEN_ONLY=1 ;;
    dp1|dp2|deep-learning) TARGETS+=("$arg") ;;
    --help|-h)
      sed -n '2,/^# ===/p' "$0" | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    *) echo "Unknown arg: $arg" >&2; exit 1 ;;
  esac
done
[[ ${#TARGETS[@]} -eq 0 ]] && TARGETS=(dp1 dp2 deep-learning)

mkdir -p "$FIXTURES_DIR"

# Derive a fixture's regen/ config from a mystmd/config.yaml. The source
# config's source_dir/output_dir/tmp_dir are relative to the config file's
# own directory (convert.sh resolves them that way), and the fixture's
# regen/ dir sits at the same depth as the mystmd/ dir — so the config works
# verbatim, with output_dir: "." landing in regen/ instead of clobbering the
# committed mystmd/ baseline. This is what makes all three fixtures validate
# identically (diff mystmd/ <-> regen/) via scripts/validate_fixture.sh.
#
# tikz mode (4th arg):
#   copy          — copy tikz_overrides.py beside the regen config (dp1/dp2:
#                   the map is a static file we can self-contain).
#   reuse-mystmd  — point tikz_overrides at ../mystmd/tikz_overrides.py (DL:
#                   the map + pre-rendered SVGs live in mystmd/ and
#                   render_tikz.py is not re-run during regen).
derive_regen_config() {
  local src_mystmd="$1" dst="$2" name="$3" tikz_mode="${4:-copy}"
  if [[ ! -f "$src_mystmd/config.yaml" ]]; then
    echo "ERROR: $src_mystmd/config.yaml not found — cannot derive regen config for $name" >&2
    return 1
  fi
  mkdir -p "$dst/regen"
  cp "$src_mystmd/config.yaml" "$dst/regen/config.yaml"
  case "$tikz_mode" in
    reuse-mystmd)
      sedi 's|^tikz_overrides:.*|tikz_overrides: ../mystmd/tikz_overrides.py|' \
        "$dst/regen/config.yaml" ;;
    copy)
      # tikz_overrides.py is referenced relative to the config dir, so it
      # must sit beside the derived regen config. Optional: an `if` (not a
      # `&&` list) so the no-file case succeeds under `set -e` while a real
      # cp failure still aborts.
      if [[ -f "$src_mystmd/tikz_overrides.py" ]]; then
        cp "$src_mystmd/tikz_overrides.py" "$dst/regen/tikz_overrides.py"
      fi ;;
  esac
}

# Re-derive only the regen/ config for a fixture, without rm -rf'ing it.
# Lets a fixture pick up a source-config change cheaply, and is the only safe
# way to (re)build the regen config for the DL fixture when it is a full git
# clone (a destructive --refresh would wipe its .git). dp1/dp2 derive from
# the sibling source repo's mystmd/; DL derives from its own committed mystmd/.
regen_only() {
  case "$1" in
    dp1) derive_regen_config "$BOOK_DP1_SRC/mystmd" "$FIXTURES_DIR/book-dp1" book-dp1 copy ;;
    dp2) derive_regen_config "$BOOK_DP2_SRC/mystmd" "$FIXTURES_DIR/book-dp2" book-dp2 copy ;;
    deep-learning)
      derive_regen_config "$FIXTURES_DIR/book-dp-deep-learning/mystmd" \
        "$FIXTURES_DIR/book-dp-deep-learning" book-dl reuse-mystmd ;;
  esac && echo "fixtures/$(_fixture_dir "$1")/regen/config.yaml re-derived"
}

_fixture_dir() {
  case "$1" in
    dp1) echo book-dp1 ;; dp2) echo book-dp2 ;;
    deep-learning) echo book-dp-deep-learning ;;
  esac
}

setup_dp1() {
  local dst="$FIXTURES_DIR/book-dp1"
  if [[ -d "$dst" && "$REFRESH" -eq 0 ]]; then
    echo "fixtures/book-dp1 exists (use --refresh to rebuild)"
    return
  fi
  if [[ ! -d "$BOOK_DP1_SRC" ]]; then
    echo "ERROR: \$BOOK_DP1_SRC not found: $BOOK_DP1_SRC" >&2
    return 1
  fi
  rm -rf "$dst"
  mkdir -p "$dst"
  # LaTeX sources (.tex + .bib in the book/ subdir)
  cp -R "$BOOK_DP1_SRC/book" "$dst/book"
  # Committed MyST output (for parity diffs)
  if [[ -d "$BOOK_DP1_SRC/mystmd" ]]; then
    mkdir -p "$dst/mystmd"
    # Only .md and config-relevant files — skip _build/, tmp/, etc.
    for f in "$BOOK_DP1_SRC/mystmd"/*.md; do
      [[ -f "$f" ]] && cp "$f" "$dst/mystmd/"
    done
  fi
  # TikZ source dir (some dp1 figures reference these)
  if [[ -d "$BOOK_DP1_SRC/tikz" ]]; then
    cp -R "$BOOK_DP1_SRC/tikz" "$dst/tikz"
  fi
  # Source-code directories — \inputminted in the .tex files points at
  # these; without them, the listing resolver emits "source not found"
  # placeholders. Sibling of book/ in dp1's layout.
  for d in "$BOOK_DP1_SRC"/source_code_*; do
    [[ -d "$d" ]] && cp -R "$d" "$dst/$(basename "$d")"
  done
  # Figures (sibling of book/). Tex sources reference these as
  # ../figures/foo.{pdf,png}.
  if [[ -d "$BOOK_DP1_SRC/figures" ]]; then
    cp -R "$BOOK_DP1_SRC/figures" "$dst/figures"
  fi
  derive_regen_config "$BOOK_DP1_SRC/mystmd" "$dst" book-dp1
  echo "fixtures/book-dp1 ready ($(find "$dst/book" -name '*.tex' | wc -l | tr -d ' ') .tex files)"
}

setup_dp2() {
  local dst="$FIXTURES_DIR/book-dp2"
  if [[ -d "$dst" && "$REFRESH" -eq 0 ]]; then
    echo "fixtures/book-dp2 exists (use --refresh to rebuild)"
    return
  fi
  if [[ ! -d "$BOOK_DP2_SRC" ]]; then
    echo "ERROR: \$BOOK_DP2_SRC not found: $BOOK_DP2_SRC" >&2
    return 1
  fi
  rm -rf "$dst"
  mkdir -p "$dst"
  # dp2 keeps .tex at repo root, not in book/
  for f in "$BOOK_DP2_SRC"/*.tex "$BOOK_DP2_SRC"/*.bib; do
    [[ -f "$f" ]] && cp "$f" "$dst/"
  done
  if [[ -d "$BOOK_DP2_SRC/figures" ]]; then
    cp -R "$BOOK_DP2_SRC/figures" "$dst/figures"
  fi
  if [[ -d "$BOOK_DP2_SRC/tikz" ]]; then
    cp -R "$BOOK_DP2_SRC/tikz" "$dst/tikz"
  fi
  if [[ -d "$BOOK_DP2_SRC/mystmd" ]]; then
    mkdir -p "$dst/mystmd"
    for f in "$BOOK_DP2_SRC/mystmd"/*.md; do
      [[ -f "$f" ]] && cp "$f" "$dst/mystmd/"
    done
  fi
  derive_regen_config "$BOOK_DP2_SRC/mystmd" "$dst" book-dp2
  echo "fixtures/book-dp2 ready ($(find "$dst" -maxdepth 1 -name '*.tex' | wc -l | tr -d ' ') .tex files)"
}

setup_dl() {
  # Deep_Learning_for_Solving_And_Estimating_Dynamic_Economic_Models.
  # Unlike dp1/dp2, the consolidated source .tex, the bibliography and the
  # rendered-TikZ map all live in different dirs, and the committed
  # mystmd/config.yaml uses output_dir: "." — so this also writes a regen/
  # config (separate output_dir) so a regen never clobbers the committed
  # mystmd/*.md baseline (the diff target). render_tikz.py (a DL-repo
  # pre-step) is NOT re-run: we reuse the already-rendered SVGs and the
  # tikz_overrides.py map shipped in mystmd/.
  local dst="$FIXTURES_DIR/book-dp-deep-learning"
  if [[ -d "$dst" && "$REFRESH" -eq 0 ]]; then
    echo "fixtures/book-dp-deep-learning exists (use --refresh to rebuild)"
    return
  fi
  if [[ ! -d "$BOOK_DL_SRC" ]]; then
    echo "ERROR: \$BOOK_DL_SRC not found: $BOOK_DL_SRC" >&2
    return 1
  fi
  rm -rf "$dst"
  mkdir -p "$dst"
  # Consolidated LaTeX source + per-figure tikz/pgf assets.
  cp -R "$BOOK_DL_SRC/lecture_script" "$dst/lecture_script"
  # Bibliography lives outside the source tree (config: ../readings/...).
  if [[ -d "$BOOK_DL_SRC/readings" ]]; then
    cp -R "$BOOK_DL_SRC/readings" "$dst/readings"
  fi
  # Committed MyST output + the canonical config + generated TikZ map +
  # rendered figures (the diff target and the inputs the regen reuses).
  if [[ -d "$BOOK_DL_SRC/mystmd" ]]; then
    mkdir -p "$dst/mystmd"
    for f in "$BOOK_DL_SRC/mystmd"/*.md; do
      [[ -f "$f" ]] && cp "$f" "$dst/mystmd/"
    done
    for f in config.yaml tikz_overrides.py myst.yml; do
      [[ -f "$BOOK_DL_SRC/mystmd/$f" ]] && cp "$BOOK_DL_SRC/mystmd/$f" "$dst/mystmd/"
    done
    [[ -d "$BOOK_DL_SRC/mystmd/figures" ]] && cp -R "$BOOK_DL_SRC/mystmd/figures" "$dst/mystmd/figures"
  fi
  # Derive the regen config from the (just-copied) committed config, reusing
  # the pre-rendered TikZ map in ../mystmd/ (render_tikz.py is not re-run).
  derive_regen_config "$dst/mystmd" "$dst" book-dl reuse-mystmd || return 1
  echo "fixtures/book-dp-deep-learning ready ($(ls "$dst/mystmd"/*.md 2>/dev/null | wc -l | tr -d ' ') baseline .md files)"
}

# --regen-only: re-derive just the regen/ config for each target, no rm -rf.
if [[ "$REGEN_ONLY" -eq 1 ]]; then
  for t in "${TARGETS[@]}"; do regen_only "$t"; done
  exit 0
fi

for t in "${TARGETS[@]}"; do
  case "$t" in
    dp1) setup_dp1 ;;
    dp2) setup_dp2 ;;
    deep-learning) setup_dl ;;
  esac
done
