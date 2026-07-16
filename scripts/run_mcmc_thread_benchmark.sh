#!/usr/bin/env bash
set -euo pipefail

ROOT="$(git rev-parse --show-toplevel)"
cd "$ROOT"

OUTPUT="results/provenance/mcmc_thread_benchmark"
SEED_MANIFEST="results/provenance/mcmc-extension-seed-checksums.txt"

[[ ! -e "$OUTPUT" ]] || {
  echo "ERROR: $OUTPUT already exists; refusing to overwrite" >&2
  exit 1
}
[[ -f "$SEED_MANIFEST" ]] || {
  echo "ERROR: missing $SEED_MANIFEST" >&2
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

TRACKED_STATUS="$(git status --porcelain --untracked-files=no)"
[[ -z "$TRACKED_STATUS" ]] || {
  echo "ERROR: tracked working tree is not clean" >&2
  printf '%s\n' "$TRACKED_STATUS" >&2
  exit 1
}

mkdir -p "$OUTPUT"

{
  echo "repository_commit=$(git rev-parse HEAD)"
  echo "repository_branch=$(git branch --show-current)"
  echo "python=$(command -v python)"
  echo "mpirun=$(command -v mpirun)"
  python --version
  mpirun --version | head -2
  lscpu
} > "$OUTPUT/execution-environment.txt"

set -o pipefail
sha256sum -c "$SEED_MANIFEST" \
  2>&1 | tee "$OUTPUT/seed-integrity.log"
SEED_STATUS=${PIPESTATUS[0]}
echo "$SEED_STATUS" > "$OUTPUT/seed-integrity-status.txt"
[[ "$SEED_STATUS" -eq 0 ]] || {
  echo "ERROR: seed checksum verification failed" >&2
  exit 1
}

DATASETS=(
  planck_lcdm_camb
  actlite_lcdm_camb
  p-actlite_lcdm_camb
)

for DATASET in "${DATASETS[@]}"; do
  for THREADS in 1 2; do
    RUN_DIR="$OUTPUT/$DATASET/threads_$THREADS"
    mkdir -p "$RUN_DIR"

    export OMP_NUM_THREADS="$THREADS"
    export OPENBLAS_NUM_THREADS=1
    export MKL_NUM_THREADS=1
    export NUMEXPR_NUM_THREADS=1
    export OMP_PROC_BIND=close
    export OMP_PLACES=cores

    echo "=== dataset=$DATASET threads=$THREADS ===" | tee "$RUN_DIR/console.log"

    set +e
    mpirun \
      --report-bindings \
      --bind-to core \
      --map-by "slot:PE=$THREADS" \
      -np 4 \
      -x COBAYA_PACKAGES_PATH \
      -x CAMB_COSMOREC_SOURCE_DIR \
      -x OMP_NUM_THREADS \
      -x OPENBLAS_NUM_THREADS \
      -x MKL_NUM_THREADS \
      -x NUMEXPR_NUM_THREADS \
      -x OMP_PROC_BIND \
      -x OMP_PLACES \
      python scripts/benchmark_mcmc_threading.py \
        --dataset "$DATASET" \
        --omp-threads "$THREADS" \
        --timed-evaluations 3 \
        --output "$RUN_DIR/verification.json" \
      2>&1 | tee -a "$RUN_DIR/console.log"
    STATUS=${PIPESTATUS[0]}
    set -e
    echo "$STATUS" > "$RUN_DIR/exit-status.txt"
    [[ "$STATUS" -eq 0 ]] || {
      echo "ERROR: benchmark failed for $DATASET threads=$THREADS" >&2
      exit "$STATUS"
    }
  done
done

python scripts/summarize_mcmc_thread_benchmark.py --root "$OUTPUT" \
  2>&1 | tee "$OUTPUT/summary-console.log"

rm -f "$OUTPUT/checksums.txt"
find "$OUTPUT" \
  -type f \
  ! -name checksums.txt \
  -print0 |
LC_ALL=C sort -z |
xargs -0 sha256sum > "$OUTPUT/checksums.txt"

sha256sum -c "$OUTPUT/checksums.txt"
cat "$OUTPUT/REPORT.md"
