#!/bin/bash
# =============================================================================
# validate_fixture.sh — one common validation process for every book fixture
# =============================================================================
#
# Runs the identical regen → validate → baseline-diff sequence against any of
# the three consumer-book fixtures, so "is this book still clean?" is one
# command rather than three bespoke invocations. Used by the architecture-
# phase work (signals B + C) and by hand.
#
# For the chosen book it:
#   (B) regenerates via convert.sh against the fixture's regen/ config, then
#       runs validate.py against that same config (structural counts, cross-ref
#       resolution, broken-math) — must exit 0;
#   (C) diffs the regenerated <stem>.md against the committed mystmd/<stem>.md
#       baseline, for every stem the config actually regenerates (chapters +
#       extra_files, honouring regen: False). Hand-curated files not in the
#       config (e.g. dp1 common_symbols.md) are excluded by construction.
#
# Signal A (the unit + golden suites) is global, not per-fixture — run it
# separately with `bash scripts/test.sh`.
#
# All three fixtures share the same layout because setup_fixtures.sh derives
# each regen/ config from the book's source mystmd/config.yaml: baseline is
# always mystmd/, regenerated output always lands in regen/ (output_dir: ".").
#
# Usage:
#   scripts/validate_fixture.sh dp1
#   scripts/validate_fixture.sh dp2
#   scripts/validate_fixture.sh deep-learning
#   scripts/validate_fixture.sh all
# =============================================================================

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
FIXTURES_DIR="$PROJECT_DIR/fixtures"

fixture_dir_for() {
  case "$1" in
    dp1)           echo "book-dp1" ;;
    dp2)           echo "book-dp2" ;;
    deep-learning) echo "book-dp-deep-learning" ;;
    *) echo "" ;;
  esac
}

validate_one() {
  local book="$1"
  local dir; dir="$(fixture_dir_for "$book")"
  if [[ -z "$dir" ]]; then
    echo "ERROR: unknown book '$book' (use dp1 | dp2 | deep-learning)" >&2
    return 2
  fi

  local fixture="$FIXTURES_DIR/$dir"
  local config="$fixture/regen/config.yaml"
  local baseline="$fixture/mystmd"

  if [[ ! -f "$config" ]]; then
    echo "ERROR: $config not found — run scripts/setup_fixtures.sh $book" >&2
    return 2
  fi
  if [[ ! -d "$baseline" ]]; then
    echo "ERROR: baseline $baseline not found" >&2
    return 2
  fi

  echo "================================================================"
  echo "  $book  ($dir)"
  echo "================================================================"

  # --- regenerate ----------------------------------------------------------
  echo "-- regenerating (convert.sh) ..."
  if ! bash "$SCRIPT_DIR/convert.sh" --config "$config" >/dev/null 2>"$fixture/regen/convert.err"; then
    echo "  FAIL: convert.sh errored — see $fixture/regen/convert.err"
    return 1
  fi

  # Where convert.sh wrote the output (output_dir resolved relative to config).
  local config_dir output_dir
  config_dir="$(dirname "$config")"
  output_dir="$(cd "$config_dir/$(python3 "$SCRIPT_DIR/_config.py" "$config" output_dir)" && pwd)"

  local rc=0

  # --- signal B: validate.py exits 0 --------------------------------------
  echo "-- (B) validate.py ..."
  if python3 "$SCRIPT_DIR/validate.py" --config "$config"; then
    echo "  (B) PASS"
  else
    echo "  (B) FAIL — validate.py exited non-zero"
    rc=1
  fi

  # --- signal C: per-stem baseline diff -----------------------------------
  echo "-- (C) baseline diff (mystmd/ <-> regen/) ..."
  local stems=() regen_flags=() i stem regen
  # chapters
  while IFS= read -r line; do stems+=("$line"); done \
    < <(python3 "$SCRIPT_DIR/_config.py" "$config" chapters.stem)
  while IFS= read -r line; do regen_flags+=("$line"); done \
    < <(python3 "$SCRIPT_DIR/_config.py" "$config" chapters.regen)
  local n_ch="${#stems[@]}"
  # extra_files
  while IFS= read -r line; do stems+=("$line"); done \
    < <(python3 "$SCRIPT_DIR/_config.py" "$config" extra_files.stem)
  while IFS= read -r line; do regen_flags+=("$line"); done \
    < <(python3 "$SCRIPT_DIR/_config.py" "$config" extra_files.regen)

  local mismatch=0 skipped=0 compared=0
  for i in "${!stems[@]}"; do
    stem="${stems[$i]}"
    [[ -n "$stem" ]] || continue
    regen="${regen_flags[$i]:-}"
    if [[ "$regen" == "False" ]]; then
      skipped=$((skipped + 1))
      continue
    fi
    local base_md="$baseline/$stem.md" regen_md="$output_dir/$stem.md"
    if [[ ! -f "$regen_md" ]]; then
      echo "  MISSING regen output: $stem.md"
      mismatch=$((mismatch + 1)); continue
    fi
    if [[ ! -f "$base_md" ]]; then
      echo "  no baseline for: $stem.md (generated but not committed)"
      mismatch=$((mismatch + 1)); continue
    fi
    compared=$((compared + 1))
    if ! diff -q "$base_md" "$regen_md" >/dev/null; then
      echo "  DIFF: $stem.md"
      mismatch=$((mismatch + 1))
    fi
  done

  if [[ "$mismatch" -eq 0 ]]; then
    echo "  (C) PASS — $compared stems byte-identical (${skipped} regen:false skipped)"
  else
    echo "  (C) FAIL — $mismatch stem(s) differ from baseline"
    echo "      inspect: diff -u $baseline/<stem>.md $output_dir/<stem>.md"
    rc=1
  fi

  echo ""
  [[ "$rc" -eq 0 ]] && echo "  RESULT: $book CLEAN" || echo "  RESULT: $book has regressions"
  echo ""
  return "$rc"
}

TARGETS=()
for arg in "$@"; do
  case "$arg" in
    all) TARGETS=(dp1 dp2 deep-learning) ;;
    dp1|dp2|deep-learning) TARGETS+=("$arg") ;;
    -h|--help) sed -n '2,/^# ===/p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "Unknown arg: $arg" >&2; exit 2 ;;
  esac
done
[[ ${#TARGETS[@]} -eq 0 ]] && { echo "Usage: validate_fixture.sh <dp1|dp2|deep-learning|all>" >&2; exit 2; }

overall=0
for t in "${TARGETS[@]}"; do
  validate_one "$t" || overall=1
done

if [[ "$overall" -eq 0 ]]; then
  echo "ALL REQUESTED FIXTURES CLEAN."
else
  echo "ONE OR MORE FIXTURES HAVE REGRESSIONS (see above)."
fi
exit "$overall"
