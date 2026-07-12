#!/usr/bin/env bash
set -euo pipefail
IFS=$'\n\t'

INSTALL_SYSTEM_DEPS=0
for arg in "$@"; do
  case "$arg" in
    --install-system-deps) INSTALL_SYSTEM_DEPS=1 ;;
    -h|--help)
      echo "Usage: $0 [--install-system-deps]"
      exit 0 ;;
    *)
      echo "ERROR: unknown argument: $arg" >&2
      exit 2 ;;
  esac
done

REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || true)"
[[ -n "$REPO_ROOT" ]] || { echo "ERROR: run inside the repository." >&2; exit 1; }
cd "$REPO_ROOT"

[[ "$(git branch --show-current)" == "confirmatory-analysis" ]] || {
  echo "ERROR: expected branch confirmatory-analysis." >&2
  exit 1
}

[[ -z "$(git status --porcelain)" ]] || {
  echo "ERROR: working tree is not clean." >&2
  git status --short >&2
  exit 1
}

PIN_FILE="results/provenance/act-lite-pin-decision.txt"
[[ -f "$PIN_FILE" ]] || { echo "ERROR: missing $PIN_FILE" >&2; exit 1; }

ACT_LITE_COMMIT="$(
  awk -F': ' '/^Selected commit:/ {print $2}' "$PIN_FILE" |
  tail -n 1 | tr -d '[:space:]'
)"
[[ "$ACT_LITE_COMMIT" =~ ^[0-9a-fA-F]{40}$ ]] || {
  echo "ERROR: invalid ACT-lite commit: '$ACT_LITE_COMMIT'" >&2
  exit 1
}
ACT_LITE_COMMIT="${ACT_LITE_COMMIT,,}"

PYTHON_BIN="${PYTHON_BIN:-python3.11}"
VENV_DIR="${VENV_DIR:-.venv-mcmc}"
COBAYA_PACKAGES_PATH="${COBAYA_PACKAGES_PATH:-$HOME/cobaya_packages_act_dr6}"
export COBAYA_PACKAGES_PATH

if [[ "$INSTALL_SYSTEM_DEPS" -eq 1 ]]; then
  command -v apt-get >/dev/null || {
    echo "ERROR: automatic system setup requires Debian/Ubuntu." >&2
    exit 1
  }
  sudo apt-get update
  sudo apt-get install -y     build-essential ca-certificates curl gfortran git     libopenmpi-dev openmpi-bin pkg-config rsync
fi

for cmd in git gfortran mpirun "$PYTHON_BIN"; do
  command -v "$cmd" >/dev/null || {
    echo "ERROR: required command not found: $cmd" >&2
    exit 1
  }
done

PYTHON_VERSION="$("$PYTHON_BIN" -c 'import platform; print(platform.python_version())')"
[[ "$PYTHON_VERSION" =~ ^3\.11(\.|$) ]] || {
  echo "ERROR: Python 3.11 required; found $PYTHON_VERSION." >&2
  exit 1
}

[[ ! -e "$VENV_DIR" ]] || {
  echo "ERROR: $VENV_DIR already exists; refusing to overwrite." >&2
  exit 1
}

PROV="results/provenance/cloud_mcmc_environment"
[[ ! -e "$PROV" ]] || {
  echo "ERROR: $PROV already exists; refusing to overwrite." >&2
  exit 1
}

mkdir -p "$PROV" "$COBAYA_PACKAGES_PATH"

STARTED_UTC="$(date -u --iso-8601=seconds)"
DEPLOYED_COMMIT="$(git rev-parse HEAD)"
HOST="$(hostname)"
LOGICAL_CPUS="$("$PYTHON_BIN" -c 'import os; print(os.cpu_count() or 0)')"

"$PYTHON_BIN" -m venv "$VENV_DIR"
PY="$VENV_DIR/bin/python"

"$PY" -m pip install --upgrade pip
"$PY" -m pip install "setuptools<82" wheel packaging
"$PY" -m pip install   "cobaya==3.5.4"   "getdist==1.7.7"   "arviz==0.23.4"   "mpi4py==4.1.2"

"$PY" -m pip install   --no-build-isolation   --no-cache-dir   "camb==1.5.0"

"$PY" -m pip install   --no-cache-dir   "git+https://github.com/ACTCollaboration/DR6-ACT-lite.git@$ACT_LITE_COMMIT"

"$PY" -m pip check

"$PY" - <<'PY'
from importlib.metadata import version

expected = {
    "cobaya": "3.5.4",
    "camb": "1.5.0",
    "getdist": "1.7.7",
    "arviz": "0.23.4",
    "mpi4py": "4.1.2",
}
for package, wanted in expected.items():
    found = version(package)
    if found != wanted:
        raise SystemExit(f"{package}: expected {wanted}, found {found}")
    print(f"{package}: {found}")

import act_dr6_cmbonly
print("act_dr6_cmbonly import: PASS")
PY

mpirun -np 4 "$PY" -c   'from mpi4py import MPI; print(f"rank={MPI.COMM_WORLD.rank} size={MPI.COMM_WORLD.size}")' |
  sort > "$PROV/mpi-four-rank-test.txt"

[[ "$(wc -l < "$PROV/mpi-four-rank-test.txt")" -eq 4 ]] || {
  echo "ERROR: MPI did not return four ranks." >&2
  exit 1
}
[[ "$(grep -c 'size=4' "$PROV/mpi-four-rank-test.txt")" -eq 4 ]] || {
  echo "ERROR: MPI size verification failed." >&2
  exit 1
}

"$PY" - "$PROV/act-lite-direct-url.json" "$ACT_LITE_COMMIT" <<'PY'
import json
import sys
from importlib.metadata import distributions
from pathlib import Path

output = Path(sys.argv[1])
expected = sys.argv[2].lower()
matches = []

for dist in distributions():
    raw = dist.read_text("direct_url.json")
    if not raw:
        continue
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        continue
    if "ACTCollaboration/DR6-ACT-lite" in str(data.get("url", "")):
        matches.append({
            "distribution": dist.metadata.get("Name", dist.name),
            "version": dist.version,
            "direct_url": data,
        })

if len(matches) != 1:
    raise SystemExit(f"Expected one ACT-lite direct URL; found {len(matches)}")

found = (
    matches[0]["direct_url"]
    .get("vcs_info", {})
    .get("commit_id", "")
    .lower()
)
if found != expected:
    raise SystemExit(f"ACT-lite commit mismatch: expected {expected}, found {found}")

output.write_text(
    json.dumps(matches[0], indent=2, sort_keys=True) + "\n",
    encoding="utf-8",
)
print(f"ACT-lite commit verified: {found}")
PY

"$PY" -m pip freeze > "$PROV/pip-freeze.txt"
"$PY" -m pip show cobaya camb getdist arviz mpi4py > "$PROV/core-packages.txt"

{
  echo "git=$(git --version)"
  echo "gfortran=$(gfortran --version | head -n 1)"
  echo "mpirun=$(mpirun --version | head -n 1)"
  echo "python=$("$PY" --version 2>&1)"
  echo "pip=$("$PY" -m pip --version)"
} > "$PROV/toolchain.txt"

FINISHED_UTC="$(date -u --iso-8601=seconds)"

"$PY" - "$PROV/environment.json" "$STARTED_UTC" "$FINISHED_UTC"   "$DEPLOYED_COMMIT" "$ACT_LITE_COMMIT" "$COBAYA_PACKAGES_PATH"   "$HOST" "$LOGICAL_CPUS" <<'PY'
import json
import platform
import sys
from importlib.metadata import version
from pathlib import Path

output, started, finished, commit, act_commit, packages_path, host, cpus = sys.argv[1:]

record = {
    "purpose": "ACT DR6 MCMC-extension software bootstrap",
    "started_utc": started,
    "finished_utc": finished,
    "hostname": host,
    "platform": platform.platform(),
    "logical_cpus": int(cpus),
    "repository_commit": commit,
    "python": platform.python_version(),
    "packages": {
        name: version(name)
        for name in (
            "cobaya", "camb", "getdist", "arviz", "mpi4py",
            "pip", "setuptools", "wheel", "packaging",
        )
    },
    "act_lite_commit": act_commit,
    "cobaya_packages_path": packages_path,
    "mpi_ranks_verified": 4,
    "likelihood_data_downloaded": False,
    "likelihood_evaluated": False,
    "mcmc_started": False,
    "target_statistic_computed": False,
}
Path(output).write_text(
    json.dumps(record, indent=2, sort_keys=True) + "\n",
    encoding="utf-8",
)
PY

find "$PROV" -type f ! -name checksums.txt -print0 |
  sort -z |
  xargs -0 sha256sum > "$PROV/checksums.txt"

echo
echo "=== CLOUD MCMC SOFTWARE ENVIRONMENT: PASS ==="
echo "Repository commit: $DEPLOYED_COMMIT"
echo "Virtual environment: $VENV_DIR"
echo "Cobaya packages path: $COBAYA_PACKAGES_PATH"
echo "ACT-lite commit: $ACT_LITE_COMMIT"
echo "MPI ranks verified: 4"
echo "Likelihood data downloaded: no"
echo "Likelihood evaluated: no"
echo "MCMC started: no"
echo
echo "Activate later with:"
echo "  source $VENV_DIR/bin/activate"
echo "  export COBAYA_PACKAGES_PATH='$COBAYA_PACKAGES_PATH'"
