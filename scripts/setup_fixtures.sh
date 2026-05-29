#!/bin/bash
# =============================================================================
# setup_fixtures.sh — Populate fixtures/ with clones of the sibling book repos
# =============================================================================
#
# Creates fixtures/book-dp1/, fixtures/book-dp2/ and
# fixtures/book-dp-deep-learning/ as real git clones of each upstream repo,
# checked out on the conversion branch (default: mystmd-conversion). All three
# fixtures therefore have the same shape: a full book working tree + its own
# .git on the branch, plus a derived regen/ config.
#
# Why clones (not selective copies): uniform "verify the fixture's own branch"
# checks across all three, and `git -C fixtures/<book> pull` to refresh. Still
# fully isolated — the clone has its own working tree and .git, so running the
# pipeline here never touches the sibling source repo. fixtures/ is gitignored,
# so each clone's nested .git is invisible to this repo. Cloning from the local
# sibling hardlinks the object store, so it's fast and space-cheap; origin is
# then repointed at the sibling's upstream so pulls track GitHub.
#
# Each fixture carries a derived regen/ config (separate output_dir) so a regen
# never clobbers the committed mystmd/ baseline that is the diff target.
#
# Usage:
#   scripts/setup_fixtures.sh                   # set up dp1, dp2 and deep-learning
#   scripts/setup_fixtures.sh dp1               # set up just dp1
#   scripts/setup_fixtures.sh --refresh         # delete + re-clone (safe: all clones)
#   scripts/setup_fixtures.sh --regen-only dp2  # re-derive just the regen/ config
#
# Env overrides: BOOK_DP1_SRC / BOOK_DP2_SRC / BOOK_DL_SRC (sibling repo paths),
# FIXTURE_BRANCH (conversion branch to check out; default mystmd-conversion).
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

# Conversion branch every fixture is checked out on.
BRANCH="${FIXTURE_BRANCH:-mystmd-conversion}"

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

# --- per-book lookups --------------------------------------------------------

_fixture_dir() {
  case "$1" in
    dp1) echo book-dp1 ;;
    dp2) echo book-dp2 ;;
    deep-learning) echo book-dp-deep-learning ;;
  esac
}

_src_for() {
  case "$1" in
    dp1) echo "$BOOK_DP1_SRC" ;;
    dp2) echo "$BOOK_DP2_SRC" ;;
    deep-learning) echo "$BOOK_DL_SRC" ;;
  esac
}

# DL reuses the pre-rendered TikZ map in ../mystmd/ (render_tikz.py is not
# re-run); dp1/dp2 self-contain their static map beside the regen config.
_tikz_mode_for() {
  [[ "$1" == deep-learning ]] && echo reuse-mystmd || echo copy
}

# --- regen config derivation -------------------------------------------------

# Derive a fixture's regen/ config from its own mystmd/config.yaml. The config's
# source_dir/output_dir/tmp_dir are relative to the config file's own directory
# (convert.sh resolves them that way), and the fixture's regen/ dir sits at the
# same depth as mystmd/ — so the config works verbatim, with output_dir: "."
# landing in regen/ instead of clobbering the committed mystmd/ baseline. This
# is what makes all three fixtures validate identically (diff mystmd/ <-> regen/)
# via scripts/validate_fixture.sh.
#
# tikz mode (4th arg):
#   copy          — copy tikz_overrides.py beside the regen config (dp1/dp2).
#   reuse-mystmd  — point tikz_overrides at ../mystmd/tikz_overrides.py (DL).
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
      # tikz_overrides.py is referenced relative to the config dir, so it must
      # sit beside the derived regen config. Use an `if` (not a `&&` list) so
      # the no-file case succeeds under `set -e` while a real cp failure aborts.
      if [[ -f "$src_mystmd/tikz_overrides.py" ]]; then
        cp "$src_mystmd/tikz_overrides.py" "$dst/regen/tikz_overrides.py"
      fi ;;
  esac
}

# Re-derive only the regen/ config for a fixture, without re-cloning it. Lets a
# fixture pick up a committed-config change cheaply (after a `git -C <fixture>
# pull`). Reads from the fixture's own mystmd/.
regen_only() {
  local dir; dir="$(_fixture_dir "$1")"
  derive_regen_config "$FIXTURES_DIR/$dir/mystmd" "$FIXTURES_DIR/$dir" "$dir" "$(_tikz_mode_for "$1")" \
    && echo "fixtures/$dir/regen/config.yaml re-derived"
}

# --- clone a fixture ---------------------------------------------------------

clone_fixture() {
  local book="$1"
  local dir; dir="$(_fixture_dir "$book")"
  local dst="$FIXTURES_DIR/$dir"
  local src; src="$(_src_for "$book")"

  if [[ -d "$dst" && "$REFRESH" -eq 0 ]]; then
    # Accept an existing fixture only if it is actually a clone on the branch
    # — otherwise a pre-PR selective-copy (no .git) or a clone on the wrong
    # branch would silently survive, and the rest of the harness assumes a
    # uniform clone on $BRANCH.
    local existing; existing="$(git -C "$dst" rev-parse --abbrev-ref HEAD 2>/dev/null || echo '')"
    if [[ -z "$existing" ]]; then
      echo "ERROR: fixtures/$dir exists but is not a git clone (pre-clone copy?). Re-run with --refresh to re-clone." >&2
      return 1
    fi
    if [[ "$existing" != "$BRANCH" ]]; then
      echo "ERROR: fixtures/$dir is on '$existing', expected '$BRANCH'. Run 'git -C fixtures/$dir checkout $BRANCH', or re-run with --refresh." >&2
      return 1
    fi
    echo "fixtures/$dir exists (clone @ $BRANCH; use --refresh to re-clone)"
    return 0
  fi
  if [[ ! -d "$src/.git" ]]; then
    echo "ERROR: source repo not found or not a git repo: $src" >&2
    return 1
  fi
  local cur; cur="$(git -C "$src" rev-parse --abbrev-ref HEAD 2>/dev/null || echo '?')"
  [[ "$cur" != "$BRANCH" ]] && \
    echo "NOTE: $src is on '$cur'; cloning its committed '$BRANCH' branch." >&2

  rm -rf "$dst"
  # Clone just the conversion branch from the local sibling (hardlinks objects
  # → fast, space-cheap), then repoint origin at the sibling's upstream so
  # `git -C <fixture> pull` tracks GitHub rather than the local path.
  if ! git clone --quiet --branch "$BRANCH" --single-branch "$src" "$dst"; then
    echo "ERROR: git clone of $src (branch $BRANCH) failed" >&2
    return 1
  fi
  local upstream; upstream="$(git -C "$src" remote get-url origin 2>/dev/null || true)"
  [[ -n "$upstream" ]] && git -C "$dst" remote set-url origin "$upstream"

  derive_regen_config "$dst/mystmd" "$dst" "$dir" "$(_tikz_mode_for "$book")" || return 1
  echo "fixtures/$dir ready (clone @ $BRANCH, $(ls "$dst/mystmd"/*.md 2>/dev/null | wc -l | tr -d ' ') baseline .md files)"
}

# --- dispatch ----------------------------------------------------------------

# --regen-only: re-derive just the regen/ config for each target, no re-clone.
if [[ "$REGEN_ONLY" -eq 1 ]]; then
  for t in "${TARGETS[@]}"; do regen_only "$t"; done
  exit 0
fi

for t in "${TARGETS[@]}"; do
  clone_fixture "$t"
done
