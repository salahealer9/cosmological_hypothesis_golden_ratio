#!/usr/bin/env bash
set -euo pipefail

if [[ "$#" -ne 3 ]]; then
  echo "Usage: $0 DATASET SEGMENT_LABEL MINIMUM_APPENDED_ROWS" >&2
  exit 2
fi

DATASET="$1"
SEGMENT_LABEL="$2"
MINIMUM_APPENDED_ROWS="$3"

ROOT="$(git rev-parse --show-toplevel)"
cd "$ROOT"

LOCK="config/mcmc_extension_execution_lock.toml"
[[ -f "$LOCK" ]] || {
  echo "ERROR: missing frozen lock $LOCK" >&2
  exit 1
}
[[ -n "${COBAYA_PACKAGES_PATH:-}" ]] || {
  echo "ERROR: COBAYA_PACKAGES_PATH is not set" >&2
  exit 1
}
[[ -n "${CAMB_COSMOREC_SOURCE_DIR:-}" ]] || {
  echo "ERROR: CAMB_COSMOREC_SOURCE_DIR is not set" >&2
  exit 1
}

THREADS="$(python - "$LOCK" <<'PY'
import sys, tomllib
with open(sys.argv[1], 'rb') as handle:
    lock = tomllib.load(handle)
print(lock['execution']['selected_threads_per_rank'])
PY
)"

case "$THREADS" in
  1|2) ;;
  *) echo "ERROR: invalid selected thread count: $THREADS" >&2; exit 1 ;;
esac

PROV="results/provenance/mcmc_extensions/$DATASET/$SEGMENT_LABEL"
[[ ! -e "$PROV" ]] || {
  echo "ERROR: provenance path already exists: $PROV" >&2
  exit 1
}

export OMP_NUM_THREADS="$THREADS"
export OPENBLAS_NUM_THREADS=1
export MKL_NUM_THREADS=1
export NUMEXPR_NUM_THREADS=1
export OMP_PROC_BIND=close
export OMP_PLACES=threads

TMP_LOG="/tmp/mcmc-extension-${DATASET}-${SEGMENT_LABEL}.log"
[[ ! -e "$TMP_LOG" ]] || {
  echo "ERROR: temporary log exists: $TMP_LOG" >&2
  exit 1
}

set -o pipefail
set +e
mpirun \
  --report-bindings \
  --map-by core \
  --bind-to core \
  -np 4 \
  -x COBAYA_PACKAGES_PATH \
  -x CAMB_COSMOREC_SOURCE_DIR \
  -x OMP_NUM_THREADS \
  -x OPENBLAS_NUM_THREADS \
  -x MKL_NUM_THREADS \
  -x NUMEXPR_NUM_THREADS \
  -x OMP_PROC_BIND \
  -x OMP_PLACES \
  python scripts/run_mcmc_extension.py \
    --dataset "$DATASET" \
    --segment-label "$SEGMENT_LABEL" \
    --minimum-appended-rows "$MINIMUM_APPENDED_ROWS" \
    --lock "$LOCK" \
  2>&1 | tee "$TMP_LOG"
STATUS=${PIPESTATUS[0]}
set -e

if [[ -d "$PROV" ]]; then
  cp "$TMP_LOG" "$PROV/console.log"
  printf '%s\n' "$STATUS" > "$PROV/exit-status.txt"
  rm -f "$PROV/checksums.txt"
  find "$PROV" \
    -type f \
    ! -name checksums.txt \
    -print0 |
  LC_ALL=C sort -z |
  xargs -0 sha256sum > "$PROV/checksums.txt"
  sha256sum -c "$PROV/checksums.txt"
fi

if [[ "$STATUS" -ne 0 ]]; then
  echo "MCMC extension failed with status $STATUS" >&2
  echo "Console log preserved at $TMP_LOG" >&2
  exit "$STATUS"
fi

rm -f "$TMP_LOG"
cat "$PROV/REPORT.md"
