#!/usr/bin/env bash
# Phase 1A acquisition: official ACT DR6.02 LCDM chains and DESI DR2 BAO likelihood data.
#
# Run from the repository root on the confirmatory-analysis branch:
#
#   bash scripts/acquire_phase1_data.sh
#
# This script performs acquisition and integrity recording only. It does not
# compute the golden-ratio residual or inspect scientific posterior results.

set -euo pipefail
IFS=$'\n\t'

REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || true)"
if [[ -z "${REPO_ROOT}" ]]; then
  echo "ERROR: run this inside the Git repository." >&2
  exit 1
fi
cd "${REPO_ROOT}"

if [[ ! -f config/analysis_plan.toml || ! -f config/confirmatory_execution_lock.toml ]]; then
  echo "ERROR: repository-root configuration files were not found." >&2
  exit 1
fi

BRANCH="$(git branch --show-current)"
if [[ "${BRANCH}" != "confirmatory-analysis" ]]; then
  echo "ERROR: expected branch confirmatory-analysis, found ${BRANCH}." >&2
  exit 1
fi

ACT_RAW="data/raw/act_dr6_02"
ACT_DERIVED="data/derived/act_dr6_02"
DESI_RAW="data/raw/desi_dr2_bao"
PROV="results/provenance/phase1_acquisition"
TMP_ROOT="$(mktemp -d)"
trap 'rm -rf "${TMP_ROOT}"' EXIT

for target in "${ACT_RAW}" "${ACT_DERIVED}" "${DESI_RAW}" "${PROV}"; do
  if [[ -d "${target}" ]] && find "${target}" -mindepth 1 -type f -print -quit | grep -q .; then
    echo "ERROR: ${target} already contains files." >&2
    echo "Refusing to overwrite an earlier acquisition." >&2
    exit 1
  fi
done

mkdir -p \
  "${ACT_RAW}/archives" \
  "${ACT_DERIVED}/chains" \
  "${DESI_RAW}/likelihood" \
  "${PROV}/http_headers"

STARTED_UTC="$(date -u --iso-8601=seconds)"
START_COMMIT="$(git rev-parse HEAD)"
LOCK_COMMIT="$(git rev-parse 'v0.1.1-confirmatory-execution-lock^{commit}')"

cat > "${PROV}/ACQUISITION_LOG.md" <<EOF
# Phase 1A acquisition log

- Started UTC: \`${STARTED_UTC}\`
- Branch: \`${BRANCH}\`
- Starting commit: \`${START_COMMIT}\`
- Execution-lock tag: \`v0.1.1-confirmatory-execution-lock\`
- Execution-lock commit: \`${LOCK_COMMIT}\`
- Scientific-result inspection during acquisition: **none**
EOF

download_act_chain() {
  local stem="$1"
  local url="https://lambda.gsfc.nasa.gov/data/act/chains/lcdm/${stem}.tar.gz"
  local dest="${ACT_RAW}/archives/${stem}.tar.gz"
  local headers="${PROV}/http_headers/${stem}.headers.txt"

  echo "Downloading ${stem} ..."
  curl \
    --fail \
    --location \
    --retry 5 \
    --retry-delay 5 \
    --connect-timeout 30 \
    --output "${dest}" \
    "${url}"

  # Header capture is provenance-only; some servers may reject HEAD requests.
  {
    echo "URL: ${url}"
    echo "Retrieved UTC: $(date -u --iso-8601=seconds)"
    curl --fail --location --silent --show-error --head "${url}" || true
  } > "${headers}"

  echo "Testing archive ${dest} ..."
  gzip -t "${dest}"
  tar -tzf "${dest}" > "${PROV}/${stem}.archive-members.txt"

  mkdir -p "${ACT_DERIVED}/chains/${stem}"
  tar -xzf "${dest}" -C "${ACT_DERIVED}/chains/${stem}"

  {
    echo
    echo "## ACT chain: ${stem}"
    echo
    echo "- URL: \`${url}\`"
    echo "- Retrieved UTC: \`$(date -u --iso-8601=seconds)\`"
    echo "- Archive bytes: \`$(stat -c '%s' "${dest}")\`"
    echo "- Archive integrity: \`gzip -t PASS\`"
  } >> "${PROV}/ACQUISITION_LOG.md"
}

download_act_chain "planck_lcdm_camb"
download_act_chain "actlite_lcdm_camb"
download_act_chain "p-actlite_lcdm_camb"

echo "Acquiring DESI DR2 BAO likelihood repository at tag v2.6 ..."
DESI_CLONE="${TMP_ROOT}/bao_data"
git clone \
  --depth 1 \
  --branch v2.6 \
  https://github.com/CobayaSampler/bao_data.git \
  "${DESI_CLONE}"

DESI_COMMIT="$(git -C "${DESI_CLONE}" rev-parse HEAD)"
DESI_TAG_OBJECT="$(git -C "${DESI_CLONE}" rev-parse v2.6^{})"

cp -a "${DESI_CLONE}/desi_bao_dr2/." "${DESI_RAW}/likelihood/"

cat > "${DESI_RAW}/SOURCE_COMMIT.txt" <<EOF
repository=https://github.com/CobayaSampler/bao_data.git
tag=v2.6
commit=${DESI_COMMIT}
tag_object_resolution=${DESI_TAG_OBJECT}
retrieved_utc=$(date -u --iso-8601=seconds)
subdirectory=desi_bao_dr2
EOF

{
  echo
  echo "## DESI DR2 BAO likelihood"
  echo
  echo "- Repository: \`CobayaSampler/bao_data\`"
  echo "- Tag: \`v2.6\`"
  echo "- Commit: \`${DESI_COMMIT}\`"
  echo "- Imported subdirectory: \`desi_bao_dr2\`"
  echo "- Retrieved UTC: \`$(date -u --iso-8601=seconds)\`"
} >> "${PROV}/ACQUISITION_LOG.md"

# Dataset-local checksum manifests. Exclude the manifests themselves.
(
  cd "${ACT_RAW}"
  find . -type f ! -name 'checksums.txt' -print0 \
    | sort -z \
    | xargs -0 sha256sum > checksums.txt
)

(
  cd "${DESI_RAW}"
  find . -type f ! -name 'checksums.txt' -print0 \
    | sort -z \
    | xargs -0 sha256sum > checksums.txt
)

# Master raw-data checksum manifest. The preregistration tag remains immutable;
# this branch records the newly acquired raw files.
find data/raw \
  -type f \
  ! -name 'checksums.txt' \
  -print0 \
  | sort -z \
  | xargs -0 sha256sum \
  > data/raw/checksums.txt

# Derived extraction manifest.
(
  cd data/derived
  find act_dr6_02 -type f ! -name 'checksums.txt' -print0 \
    | sort -z \
    | xargs -0 sha256sum > checksums.txt
)

FINISHED_UTC="$(date -u --iso-8601=seconds)"
{
  echo
  echo "## Completion"
  echo
  echo "- Finished UTC: \`${FINISHED_UTC}\`"
  echo "- Raw master checksum manifest: \`data/raw/checksums.txt\`"
  echo "- Derived checksum manifest: \`data/derived/checksums.txt\`"
} >> "${PROV}/ACQUISITION_LOG.md"

cat > "${PROV}/SUMMARY.txt" <<EOF
Phase 1A acquisition completed
started_utc=${STARTED_UTC}
finished_utc=${FINISHED_UTC}
branch=${BRANCH}
starting_commit=${START_COMMIT}
execution_lock_commit=${LOCK_COMMIT}
act_archives=3
desi_bao_repository_tag=v2.6
desi_bao_repository_commit=${DESI_COMMIT}
EOF

echo
echo "=== ACQUISITION COMPLETE ==="
cat "${PROV}/SUMMARY.txt"
echo
echo "ACT archive checksums:"
cat "${ACT_RAW}/checksums.txt"
echo
echo "DESI source:"
cat "${DESI_RAW}/SOURCE_COMMIT.txt"
echo
echo "No scientific posterior statistic was computed."
