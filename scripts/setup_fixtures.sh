#!/bin/bash
# =============================================================================
# setup_fixtures.sh — Populate fixtures/ with local copies of sibling book repos
# =============================================================================
#
# Creates fixtures/book-dp1/ and fixtures/book-dp2/ by copying just the parts
# of each upstream repo needed to run the parity tests:
#   - the LaTeX sources we convert from
#   - the committed mystmd/ output (so we can diff against it)
#   - any TikZ overrides / scripts the test config references
#
# Why copies rather than symlinks: the user prefers fully-isolated copies so
# running the pipeline here never touches an in-progress branch in the
# upstream repos. fixtures/ is gitignored.
#
# Usage:
#   scripts/setup_fixtures.sh            # set up both dp1 and dp2
#   scripts/setup_fixtures.sh dp1        # set up just dp1
#   scripts/setup_fixtures.sh dp2        # set up just dp2
#   scripts/setup_fixtures.sh --refresh  # delete + rebuild
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
FIXTURES_DIR="$PROJECT_DIR/fixtures"

# Where to find the upstream repos. Override with env vars if your layout differs.
BOOK_DP1_SRC="${BOOK_DP1_SRC:-$PROJECT_DIR/../book-dp1}"
BOOK_DP2_SRC="${BOOK_DP2_SRC:-$PROJECT_DIR/../book-dp2}"

REFRESH=0
TARGETS=()

for arg in "$@"; do
  case "$arg" in
    --refresh) REFRESH=1 ;;
    dp1|dp2)   TARGETS+=("$arg") ;;
    --help|-h)
      sed -n '2,/^# ===/p' "$0" | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    *) echo "Unknown arg: $arg" >&2; exit 1 ;;
  esac
done
[[ ${#TARGETS[@]} -eq 0 ]] && TARGETS=(dp1 dp2)

mkdir -p "$FIXTURES_DIR"

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
  echo "fixtures/book-dp2 ready ($(find "$dst" -maxdepth 1 -name '*.tex' | wc -l | tr -d ' ') .tex files)"
}

for t in "${TARGETS[@]}"; do
  case "$t" in
    dp1) setup_dp1 ;;
    dp2) setup_dp2 ;;
  esac
done
