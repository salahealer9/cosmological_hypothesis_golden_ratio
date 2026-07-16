#!/usr/bin/env bash
set -euo pipefail
IFS=$'\n\t'

INSTALL_SYSTEM_DEPS=0
for arg in "$@"; do
  case "$arg" in
    --install-system-deps) INSTALL_SYSTEM_DEPS=1 ;;
    -h|--help)
      cat <<'USAGE'
Usage: scripts/setup_cloud_mcmc_environment.sh [--install-system-deps]

Environment overrides:
  PYTHON_BIN                 default: python3.11
  VENV_DIR                   default: .venv-mcmc
  COBAYA_PACKAGES_PATH       default: $HOME/cobaya_packages_act_dr6
  COSMOLOGY_SOFTWARE_ROOT    default: /opt/cosmology-software
USAGE
      exit 0 ;;
    *)
      echo "ERROR: unknown argument: $arg" >&2
      exit 2 ;;
  esac
done

REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || true)"
[[ -n "$REPO_ROOT" ]] || {
  echo "ERROR: run inside the repository." >&2
  exit 1
}
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
[[ -f "$PIN_FILE" ]] || {
  echo "ERROR: missing $PIN_FILE" >&2
  exit 1
}

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
COSMOLOGY_SOFTWARE_ROOT="${COSMOLOGY_SOFTWARE_ROOT:-/opt/cosmology-software}"
export COBAYA_PACKAGES_PATH

COSMOREC_VERSION="2.0.3b"
COSMOREC_ARCHIVE_NAME="CosmoRec.v${COSMOREC_VERSION}.tar.gz"
COSMOREC_URL="https://www.cita.utoronto.ca/~jchluba/Recombination/_Downloads_/${COSMOREC_ARCHIVE_NAME}"
COSMOREC_ARCHIVE_SHA256="2afb82b5512f7158a0291d3a73c6520455f0e55957f2965dccc5eef82af8da1b"
COSMOREC_ARCHIVE="$COSMOLOGY_SOFTWARE_ROOT/$COSMOREC_ARCHIVE_NAME"
COSMOREC_DIR="$COSMOLOGY_SOFTWARE_ROOT/CosmoRec.v${COSMOREC_VERSION}"

CAMB_VERSION="1.5.0"
CAMB_COMMIT="28e4036519155531f4ed9a4e1d8afb1579d2de11"
CAMB_FORUTILS_COMMIT="fcaff9d176c0ec6a9c63b036465fbb6be6722338"
CAMB_DIR="$COSMOLOGY_SOFTWARE_ROOT/CAMB-${CAMB_VERSION}-cosmorec"

PROV="results/provenance/cloud_mcmc_environment"

if [[ "$INSTALL_SYSTEM_DEPS" -eq 1 ]]; then
  command -v apt-get >/dev/null || {
    echo "ERROR: automatic system setup requires Debian/Ubuntu." >&2
    exit 1
  }
  sudo apt-get update
  sudo apt-get install -y \
    build-essential \
    ca-certificates \
    curl \
    gfortran \
    git \
    libgsl-dev \
    libopenmpi-dev \
    openmpi-bin \
    pkg-config \
    rsync \
    tar

  sudo install -d \
    -o "$USER" \
    -g "$(id -gn)" \
    "$COSMOLOGY_SOFTWARE_ROOT"
fi

for cmd in curl git g++ gfortran make mpirun sha256sum tar "$PYTHON_BIN"; do
  command -v "$cmd" >/dev/null || {
    echo "ERROR: required command not found: $cmd" >&2
    exit 1
  }
done

[[ -d "$COSMOLOGY_SOFTWARE_ROOT" ]] || {
  echo "ERROR: software root does not exist: $COSMOLOGY_SOFTWARE_ROOT" >&2
  echo "Run with --install-system-deps or create it as a user-writable directory." >&2
  exit 1
}
[[ -w "$COSMOLOGY_SOFTWARE_ROOT" ]] || {
  echo "ERROR: software root is not writable: $COSMOLOGY_SOFTWARE_ROOT" >&2
  exit 1
}

PYTHON_VERSION="$("$PYTHON_BIN" -c 'import platform; print(platform.python_version())')"
[[ "$PYTHON_VERSION" =~ ^3\.11(\.|$) ]] || {
  echo "ERROR: Python 3.11 required; found $PYTHON_VERSION." >&2
  exit 1
}

for path in \
  "$VENV_DIR" \
  "$PROV" \
  "$COSMOREC_ARCHIVE" \
  "$COSMOREC_DIR" \
  "$CAMB_DIR"
do
  [[ ! -e "$path" ]] || {
    echo "ERROR: $path already exists; refusing to overwrite." >&2
    exit 1
  }
done

mkdir -p "$PROV" "$COBAYA_PACKAGES_PATH"

STARTED_UTC="$(date -u --iso-8601=seconds)"
DEPLOYED_COMMIT="$(git rev-parse HEAD)"
HOST="$(hostname)"
LOGICAL_CPUS="$("$PYTHON_BIN" -c 'import os; print(os.cpu_count() or 0)')"

"$PYTHON_BIN" -m venv "$VENV_DIR"
PY="$VENV_DIR/bin/python"

"$PY" -m pip install --upgrade pip
"$PY" -m pip install "setuptools<82" wheel packaging
"$PY" -m pip install \
  "cobaya==3.5.4" \
  "getdist==1.7.7" \
  "arviz==0.23.4" \
  "mpi4py==4.1.2"

# ---------------------------------------------------------------------------
# Build the exact CAMB 1.5.0 + CosmoRec 2.0.3b variant required by the
# released ACT DR6 chain YAML files. A stock CAMB wheel is insufficient.
# ---------------------------------------------------------------------------

curl --fail --location --retry 3 \
  --output "$COSMOREC_ARCHIVE" \
  "$COSMOREC_URL"

printf '%s  %s\n' "$COSMOREC_ARCHIVE_SHA256" "$COSMOREC_ARCHIVE" \
  > "$PROV/cosmorec-archive-expected-sha256.txt"
sha256sum "$COSMOREC_ARCHIVE" \
  > "$PROV/cosmorec-archive-observed-sha256.txt"
printf '%s  %s\n' "$COSMOREC_ARCHIVE_SHA256" "$COSMOREC_ARCHIVE" |
  sha256sum -c - |
  tee "$PROV/cosmorec-archive-verification.txt"

tar -xzf "$COSMOREC_ARCHIVE" -C "$COSMOLOGY_SOFTWARE_ROOT"
[[ -f "$COSMOREC_DIR/Makefile.in" ]] || {
  echo "ERROR: CosmoRec extraction did not produce $COSMOREC_DIR/Makefile.in" >&2
  exit 1
}

cp "$COSMOREC_DIR/Makefile.in" "$PROV/CosmoRec-Makefile.in.upstream"

"$PY" - "$COSMOREC_DIR/Makefile.in" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
lines = path.read_text(encoding="utf-8").splitlines()
original = "CXXFLAGS = -Wall -pedantic -O2"
replacement = "CXXFLAGS = -Wall -pedantic -O2 -fPIC"
matches = [i for i, line in enumerate(lines) if line.strip() == original]
if len(matches) != 1:
    raise SystemExit(
        f"Expected exactly one exact assignment {original!r}; found {len(matches)}"
    )
i = matches[0]
indent = lines[i][: len(lines[i]) - len(lines[i].lstrip())]
lines[i] = indent + replacement
path.write_text("\n".join(lines) + "\n", encoding="utf-8")
print(f"Patched line {i + 1}: {lines[i]}")
PY

cp "$COSMOREC_DIR/Makefile.in" "$PROV/CosmoRec-Makefile.in.patched"
diff -u \
  "$PROV/CosmoRec-Makefile.in.upstream" \
  "$PROV/CosmoRec-Makefile.in.patched" \
  > "$PROV/CosmoRec-fPIC.patch" || true

grep -Fqx 'CXXFLAGS = -Wall -pedantic -O2 -fPIC' \
  "$COSMOREC_DIR/Makefile.in" || {
    echo "ERROR: exact CosmoRec -fPIC assignment not present." >&2
    exit 1
  }

(
  cd "$COSMOREC_DIR"
  make all
) 2>&1 | tee "$PROV/cosmorec-build.log"

[[ -s "$COSMOREC_DIR/libCosmoRec.a" ]] || {
  echo "ERROR: CosmoRec static library was not produced." >&2
  exit 1
}

PIC_COMPILE_TOTAL="$(
  grep -cE '^g\+\+ .* -c ' "$PROV/cosmorec-build.log" || true
)"
NON_PIC_COMPILES="$(
  grep -E '^g\+\+ .* -c ' "$PROV/cosmorec-build.log" |
  grep -vc -- '-fPIC' || true
)"
[[ "$PIC_COMPILE_TOTAL" -gt 0 ]] || {
  echo "ERROR: no CosmoRec C++ compilation commands were recorded." >&2
  exit 1
}
[[ "$NON_PIC_COMPILES" -eq 0 ]] || {
  echo "ERROR: $NON_PIC_COMPILES CosmoRec compile commands lacked -fPIC." >&2
  exit 1
}

# Clone and pin CAMB independently of mutable tags.
git clone --recursive https://github.com/cmbant/CAMB.git "$CAMB_DIR"
git -C "$CAMB_DIR" checkout --detach "$CAMB_COMMIT"
git -C "$CAMB_DIR" submodule sync --recursive
git -C "$CAMB_DIR" submodule update --init --recursive

[[ "$(git -C "$CAMB_DIR" rev-parse HEAD)" == "$CAMB_COMMIT" ]] || {
  echo "ERROR: CAMB commit mismatch." >&2
  exit 1
}
[[ "$(git -C "$CAMB_DIR/forutils" rev-parse HEAD)" == "$CAMB_FORUTILS_COMMIT" ]] || {
  echo "ERROR: CAMB forutils submodule commit mismatch." >&2
  exit 1
}
[[ "$(git -C "$CAMB_DIR" describe --tags --exact-match)" == "$CAMB_VERSION" ]] || {
  echo "ERROR: CAMB commit is not exact tag $CAMB_VERSION." >&2
  exit 1
}

cp "$CAMB_DIR/fortran/Makefile_main" "$PROV/CAMB-Makefile_main.upstream"

"$PY" - "$CAMB_DIR/fortran/Makefile_main" "$COSMOREC_DIR" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
cosmorec = Path(sys.argv[2]).resolve()
text = path.read_text(encoding="utf-8")
for forbidden in (
    "RECOMBINATION_FILES = recfast cosmorec",
    "COSMOREC_PATH =",
):
    if forbidden in text:
        raise SystemExit(f"Refusing to duplicate existing setting: {forbidden}")
prefix = (
    "RECOMBINATION_FILES = recfast cosmorec\n"
    f"COSMOREC_PATH = {cosmorec}\n\n"
)
path.write_text(prefix + text, encoding="utf-8")
print(prefix, end="")
PY

cp "$CAMB_DIR/fortran/Makefile_main" "$PROV/CAMB-Makefile_main.patched"
diff -u \
  "$PROV/CAMB-Makefile_main.upstream" \
  "$PROV/CAMB-Makefile_main.patched" \
  > "$PROV/CAMB-CosmoRec.patch" || true

(
  cd "$CAMB_DIR"
  "$PY" setup.py make
) 2>&1 | tee "$PROV/camb-cosmorec-build.log"

[[ -s "$CAMB_DIR/camb/camblib.so" ]] || {
  echo "ERROR: CAMB CosmoRec shared library was not produced." >&2
  exit 1
}

PYTHONPATH="$CAMB_DIR" "$PY" - <<'PY' |
  tee "$PROV/camb-cosmorec-source-capability.txt"
import camb
params = camb.CAMBparams()
params.set_classes(recombination_model="CosmoRec")
print("CAMB module version:", camb.__version__)
print("CAMB imported from:", camb.__file__)
print("Recombination class:", type(params.Recomb).__name__)
assert camb.__version__ == "1.5.0"
assert type(params.Recomb).__name__ == "CosmoRec"
print("CAMB 1.5.0 + CosmoRec source capability: PASS")
PY

"$PY" -m pip install \
  --no-build-isolation \
  --no-deps \
  -e "$CAMB_DIR"

"$PY" - "$CAMB_DIR" "$PROV/camb-direct-url.json" <<'PY'
import json
import sys
from importlib.metadata import distribution, version
from pathlib import Path
from urllib.parse import unquote, urlparse

expected_root = Path(sys.argv[1]).resolve()
output = Path(sys.argv[2])

import camb

params = camb.CAMBparams()
params.set_classes(recombination_model="CosmoRec")
module_path = Path(camb.__file__).resolve()
raw = distribution("camb").read_text("direct_url.json")
if raw is None:
    raise SystemExit("No CAMB direct_url.json found")
record = json.loads(raw)
url = record.get("url", "")
parsed = urlparse(url)
source_path = Path(unquote(parsed.path)).resolve() if parsed.scheme == "file" else None
editable = bool(record.get("dir_info", {}).get("editable"))

checks = {
    "metadata_version": version("camb") == "1.5.0",
    "module_version": camb.__version__ == "1.5.0",
    "module_inside_source": module_path.is_relative_to(expected_root),
    "source_url_matches": source_path == expected_root,
    "editable": editable,
    "cosmorec_class": type(params.Recomb).__name__ == "CosmoRec",
}
if not all(checks.values()):
    raise SystemExit(f"CAMB CosmoRec installed capability failed: {checks}")

output.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")
for name, passed in checks.items():
    print(f"{name}: {'PASS' if passed else 'FAIL'}")
print("Installed CAMB 1.5.0 + CosmoRec capability: PASS")
PY

ldd "$CAMB_DIR/camb/camblib.so" > "$PROV/camb-cosmorec-linked-libraries.txt"
if grep -q 'not found' "$PROV/camb-cosmorec-linked-libraries.txt"; then
  echo "ERROR: unresolved CAMB shared-library dependency." >&2
  cat "$PROV/camb-cosmorec-linked-libraries.txt" >&2
  exit 1
fi

sha256sum \
  "$COSMOREC_ARCHIVE" \
  "$COSMOREC_DIR/libCosmoRec.a" \
  "$CAMB_DIR/camb/camblib.so" \
  > "$PROV/camb-cosmorec-artifact-sha256.txt"

git -C "$CAMB_DIR" rev-parse HEAD > "$PROV/camb-source-commit.txt"
git -C "$CAMB_DIR" describe --tags --exact-match > "$PROV/camb-source-tag.txt"
git -C "$CAMB_DIR" submodule status --recursive > "$PROV/camb-submodules.txt"

"$PY" -m pip install \
  --no-cache-dir \
  "git+https://github.com/ACTCollaboration/DR6-ACT-lite.git@$ACT_LITE_COMMIT"

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

mpirun -np 4 "$PY" -c \
  'from mpi4py import MPI; print(f"rank={MPI.COMM_WORLD.rank} size={MPI.COMM_WORLD.size}")' |
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
found = matches[0]["direct_url"].get("vcs_info", {}).get("commit_id", "").lower()
if found != expected:
    raise SystemExit(f"ACT-lite commit mismatch: expected {expected}, found {found}")
output.write_text(json.dumps(matches[0], indent=2, sort_keys=True) + "\n")
print(f"ACT-lite commit verified: {found}")
PY

"$PY" -m pip freeze > "$PROV/pip-freeze.txt"
"$PY" -m pip show cobaya camb getdist arviz mpi4py > "$PROV/core-packages.txt"

{
  echo "git=$(git --version)"
  echo "g++=$(g++ --version | head -n 1)"
  echo "gfortran=$(gfortran --version | head -n 1)"
  echo "mpirun=$(mpirun --version | head -n 1)"
  echo "python=$("$PY" --version 2>&1)"
  echo "pip=$("$PY" -m pip --version)"
} > "$PROV/toolchain.txt"

FINISHED_UTC="$(date -u --iso-8601=seconds)"

"$PY" - \
  "$PROV/environment.json" \
  "$STARTED_UTC" \
  "$FINISHED_UTC" \
  "$DEPLOYED_COMMIT" \
  "$ACT_LITE_COMMIT" \
  "$COBAYA_PACKAGES_PATH" \
  "$HOST" \
  "$LOGICAL_CPUS" \
  "$COSMOLOGY_SOFTWARE_ROOT" \
  "$COSMOREC_VERSION" \
  "$COSMOREC_ARCHIVE_SHA256" \
  "$COSMOREC_ARCHIVE" \
  "$COSMOREC_DIR" \
  "$CAMB_COMMIT" \
  "$CAMB_FORUTILS_COMMIT" \
  "$CAMB_DIR" <<'PY'
import hashlib
import json
import platform
import sys
from importlib.metadata import version
from pathlib import Path

(
    output, started, finished, commit, act_commit, packages_path, host, cpus,
    software_root, cosmorec_version, cosmorec_sha, cosmorec_archive,
    cosmorec_dir, camb_commit, forutils_commit, camb_dir,
) = sys.argv[1:]

def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()

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
    "software_root": software_root,
    "camb_cosmorec_build": {
        "capability_verified": True,
        "camb_version": "1.5.0",
        "camb_commit": camb_commit,
        "forutils_commit": forutils_commit,
        "camb_source_dir": camb_dir,
        "camb_shared_library_sha256": sha256(Path(camb_dir) / "camb/camblib.so"),
        "installation_mode": "editable_local_source",
        "recombination_class": "CosmoRec",
        "cosmorec_version": cosmorec_version,
        "cosmorec_archive_sha256": cosmorec_sha,
        "cosmorec_archive": cosmorec_archive,
        "cosmorec_source_dir": cosmorec_dir,
        "cosmorec_static_library_sha256": sha256(
            Path(cosmorec_dir) / "libCosmoRec.a"
        ),
        "fPIC_required_and_verified": True,
    },
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
  LC_ALL=C sort -z |
  xargs -0 sha256sum > "$PROV/checksums.txt"

echo
echo "=== CLOUD MCMC SOFTWARE ENVIRONMENT: PASS ==="
echo "Repository commit: $DEPLOYED_COMMIT"
echo "Virtual environment: $VENV_DIR"
echo "Cobaya packages path: $COBAYA_PACKAGES_PATH"
echo "ACT-lite commit: $ACT_LITE_COMMIT"
echo "CAMB commit: $CAMB_COMMIT"
echo "CAMB CosmoRec capability: PASS"
echo "CosmoRec version: $COSMOREC_VERSION"
echo "CosmoRec archive SHA-256: $COSMOREC_ARCHIVE_SHA256"
echo "MPI ranks verified: 4"
echo "Likelihood data downloaded: no"
echo "Likelihood evaluated: no"
echo "MCMC started: no"
echo
echo "Activate later with:"
echo "  source $VENV_DIR/bin/activate"
echo "  export COBAYA_PACKAGES_PATH='$COBAYA_PACKAGES_PATH'"
