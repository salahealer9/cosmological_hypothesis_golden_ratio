#!/usr/bin/env python3
"""Shared target-blind runtime gates for the locked ACT/Planck MCMC work.

This module centralizes the three compatibility corrections discovered during
likelihood smoke testing and the software identity checks needed before any
benchmark or chain extension:

* CAMB 1.5.0 must be the pinned editable source build with CosmoRec 2.0.3b;
* ACT DR6 CMB-only must use the public v1.0 data file;
* Cobaya 3.5.4 must advertise the existing ``CAMBdata.taurend`` field.

It does not compute the project target statistic or inspect target residuals.
"""

from __future__ import annotations

import copy
import hashlib
import inspect
import json
import os
import subprocess
from importlib.metadata import distribution, distributions, version
from pathlib import Path
from typing import Any, Mapping, MutableMapping
from urllib.parse import unquote, urlparse

EXPECTED_PACKAGE_VERSIONS = {
    "cobaya": "3.5.4",
    "camb": "1.5.0",
    "getdist": "1.7.7",
    "arviz": "0.23.4",
    "mpi4py": "4.1.2",
}

EXPECTED_CAMB_COMMIT = "28e4036519155531f4ed9a4e1d8afb1579d2de11"
EXPECTED_CAMB_SOURCE = Path("/opt/cosmology-software/CAMB-1.5.0-cosmorec")
EXPECTED_ACT_LITE_COMMIT = "880eacb40d66722eb1c32d7b5621e91662b4d808"

ACT_LIKELIHOOD_NAME = "act_dr6_cmbonly.ACTDR6CMBonly"
EXPECTED_ACT_DATA_VERSION = "v1.0"
EXPECTED_ACT_INPUT_FILE = "dr6_data_cmbonly.fits"
LEGACY_ACT_INPUT_FILE = "dr6_data_cmb_sacc_oct22.fits"
ALLOWED_SERIALIZED_ACT_VERSIONS = {None, EXPECTED_ACT_DATA_VERSION}
ALLOWED_SERIALIZED_ACT_INPUT_FILES = {
    None,
    EXPECTED_ACT_INPUT_FILE,
    LEGACY_ACT_INPUT_FILE,
}
EXPECTED_ACT_DATA_RELATIVE_PATH = (
    Path("data/ACTDR6CMBonly")
    / EXPECTED_ACT_DATA_VERSION
    / EXPECTED_ACT_INPUT_FILE
)


DATASETS: dict[str, dict[str, Any]] = {
    "planck_lcdm_camb": {
        "directory": "data/derived/act_dr6_02/mcmc_extension_seed/planck_lcdm_camb",
        "prefix": "planck-camb-lcdm",
        "runtime_template": "config/mcmc_extension_runtime_inputs/planck_lcdm_camb.yaml",
        "likelihoods": [
            "planck_2018_lowl.TT",
            "planck_2018_lowl.EE_sroll2",
            "act_dr6_cmbonly.PlanckActCut",
        ],
    },
    "actlite_lcdm_camb": {
        "directory": "data/derived/act_dr6_02/mcmc_extension_seed/actlite_lcdm_camb",
        "prefix": "act-camb-lcdm",
        "runtime_template": "config/mcmc_extension_runtime_inputs/actlite_lcdm_camb.yaml",
        "likelihoods": [
            "planck_2018_lowl.EE_sroll2",
            "act_dr6_cmbonly.ACTDR6CMBonly",
        ],
    },
    "p-actlite_lcdm_camb": {
        "directory": "data/derived/act_dr6_02/mcmc_extension_seed/p-actlite_lcdm_camb",
        "prefix": "p-act-camb-lcdm",
        "runtime_template": "config/mcmc_extension_runtime_inputs/p-actlite_lcdm_camb.yaml",
        "likelihoods": [
            "planck_2018_lowl.TT",
            "planck_2018_lowl.EE_sroll2",
            "act_dr6_cmbonly.PlanckActCut",
            "act_dr6_cmbonly.ACTDR6CMBonly",
        ],
    },
}

THREAD_ENVIRONMENT_KEYS = (
    "OMP_NUM_THREADS",
    "OPENBLAS_NUM_THREADS",
    "MKL_NUM_THREADS",
    "NUMEXPR_NUM_THREADS",
)


def sha256_file(path: Path) -> str:
    """Return the SHA-256 digest of *path*."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def run_command(
    args: list[str],
    *,
    cwd: Path | None = None,
    check: bool = False,
) -> subprocess.CompletedProcess[str]:
    """Run a text command without invoking a shell."""
    return subprocess.run(
        args,
        cwd=cwd,
        text=True,
        capture_output=True,
        check=check,
    )


def _direct_url_record(package_name: str) -> dict[str, Any]:
    raw = distribution(package_name).read_text("direct_url.json")
    if raw is None:
        raise RuntimeError(
            f"{package_name} has no direct_url.json; the installation identity "
            "cannot be verified"
        )
    record = json.loads(raw)
    if not isinstance(record, dict):
        raise RuntimeError(f"Malformed direct_url.json for {package_name}")
    return record


def _file_url_path(record: Mapping[str, Any]) -> Path | None:
    parsed = urlparse(str(record.get("url", "")))
    if parsed.scheme != "file":
        return None
    return Path(unquote(parsed.path)).resolve()


def verify_package_versions() -> dict[str, Any]:
    """Require the exact locked Python package versions."""
    installed = {
        name: version(name)
        for name in EXPECTED_PACKAGE_VERSIONS
    }
    checks = {
        name: installed[name] == wanted
        for name, wanted in EXPECTED_PACKAGE_VERSIONS.items()
    }
    if not all(checks.values()):
        raise RuntimeError(
            f"Locked package-version gate failed: checks={checks}, "
            f"installed={installed}"
        )
    return {
        "expected": dict(EXPECTED_PACKAGE_VERSIONS),
        "installed": installed,
        "checks": checks,
    }


def verify_act_lite_installation() -> dict[str, Any]:
    """Verify that exactly one installed distribution records the pinned commit."""
    matches: list[dict[str, Any]] = []
    for dist in distributions():
        raw = dist.read_text("direct_url.json")
        if not raw:
            continue
        try:
            record = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if "ACTCollaboration/DR6-ACT-lite" not in str(record.get("url", "")):
            continue
        matches.append(
            {
                "distribution_name": dist.metadata.get("Name", dist.name),
                "distribution_version": dist.version,
                "direct_url": record,
            }
        )
    if len(matches) != 1:
        raise RuntimeError(
            f"Expected exactly one ACT-lite installation; found {len(matches)}"
        )

    match = matches[0]
    record = match["direct_url"]
    vcs_info = record.get("vcs_info") or {}
    commit_id = str(vcs_info.get("commit_id", "")).lower()
    requested_revision = str(vcs_info.get("requested_revision", "")).lower()
    checks = {
        "commit_matches": commit_id == EXPECTED_ACT_LITE_COMMIT,
        "requested_revision_matches_or_unspecified": requested_revision in {
            "",
            EXPECTED_ACT_LITE_COMMIT,
        },
        "git_vcs_record": vcs_info.get("vcs") == "git",
    }
    if not all(checks.values()):
        raise RuntimeError(
            f"ACT-lite installation gate failed: {checks}; record={record}"
        )
    return {
        "expected_commit": EXPECTED_ACT_LITE_COMMIT,
        "installed_commit": commit_id,
        "distribution_name": match["distribution_name"],
        "distribution_version": match["distribution_version"],
        "direct_url": record,
        "checks": checks,
    }


def verify_camb_cosmorec_capability(
    expected_source: Path | None = None,
) -> dict[str, Any]:
    """Reject a stock CAMB wheel or an unresolved CosmoRec build."""
    import camb

    source = (
        expected_source
        or Path(
            os.environ.get(
                "CAMB_COSMOREC_SOURCE_DIR",
                str(EXPECTED_CAMB_SOURCE),
            )
        )
    ).resolve()
    if not source.is_dir():
        raise RuntimeError(f"Pinned CAMB source directory is missing: {source}")

    module_path = Path(camb.__file__).resolve()
    params = camb.CAMBparams()
    params.set_classes(recombination_model="CosmoRec")

    direct_url = _direct_url_record("camb")
    direct_source = _file_url_path(direct_url)
    editable = bool(direct_url.get("dir_info", {}).get("editable"))

    commit_result = run_command(["git", "rev-parse", "HEAD"], cwd=source)
    installed_commit = (
        commit_result.stdout.strip()
        if commit_result.returncode == 0
        else ""
    )

    camblib = source / "camb/camblib.so"
    ldd_result = run_command(["ldd", str(camblib)]) if camblib.is_file() else None
    libraries_resolved = bool(
        ldd_result
        and ldd_result.returncode == 0
        and "not found" not in ldd_result.stdout
        and "not found" not in ldd_result.stderr
    )

    checks = {
        "metadata_version": version("camb") == "1.5.0",
        "module_version": camb.__version__ == "1.5.0",
        "module_inside_pinned_source": module_path.is_relative_to(source),
        "editable_source_path_matches": editable and direct_source == source,
        "source_commit_matches": installed_commit == EXPECTED_CAMB_COMMIT,
        "cosmorec_class_available": type(params.Recomb).__name__ == "CosmoRec",
        "camblib_exists": camblib.is_file(),
        "linked_libraries_resolved": libraries_resolved,
    }
    if not all(checks.values()):
        raise RuntimeError(f"CAMB-CosmoRec capability gate failed: {checks}")

    return {
        "expected_source": str(source),
        "module_path": str(module_path),
        "expected_commit": EXPECTED_CAMB_COMMIT,
        "installed_commit": installed_commit,
        "recombination_class": type(params.Recomb).__name__,
        "direct_url": direct_url,
        "camblib_sha256": sha256_file(camblib),
        "checks": checks,
        "numerical_spectra_computed": False,
    }


def install_cobaya_taurend_capability_shim() -> dict[str, Any]:
    """Advertise the existing ``CAMBdata.taurend`` field process-locally."""
    import camb
    from cobaya.theories.camb.camb import CAMB as CobayaCAMB

    fields = {field[0] for field in camb.CAMBdata._fields_ if field}
    if "taurend" not in fields:
        raise RuntimeError("Pinned CAMBdata does not expose taurend")

    current = CobayaCAMB.get_can_provide_params
    if getattr(current, "_golden_ratio_taurend_shim", False):
        return {
            "parameter": "taurend",
            "already_installed": True,
            "process_local_only": True,
        }

    source_file_raw = inspect.getsourcefile(CobayaCAMB)
    if source_file_raw is None:
        raise RuntimeError("Could not locate Cobaya's CAMB component source")
    source_file = Path(source_file_raw).resolve()
    if not source_file.is_file():
        raise RuntimeError(f"Missing Cobaya CAMB source: {source_file}")

    original = current

    def patched_get_can_provide_params(self):
        names = set(original(self))
        names.add("taurend")
        return names

    patched_get_can_provide_params.__name__ = (
        original.__name__ + "_with_taurend"
    )
    patched_get_can_provide_params.__doc__ = (
        "Process-local compatibility shim adding CAMBdata.taurend."
    )
    patched_get_can_provide_params._golden_ratio_taurend_shim = True
    CobayaCAMB.get_can_provide_params = patched_get_can_provide_params

    return {
        "parameter": "taurend",
        "already_installed": False,
        "cobaya_component": "cobaya.theories.camb.camb.CAMB",
        "patched_method": "get_can_provide_params",
        "installed_source_file": str(source_file),
        "installed_source_sha256": sha256_file(source_file),
        "cambdata_field_present": True,
        "process_local_only": True,
        "source_file_modified": False,
        "changes_camb_calculation": False,
        "changes_likelihood_calculation": False,
    }


def normalize_act_runtime_info(
    info: Mapping[str, Any],
    packages_path: Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return a deep-copied info dictionary with pinned ACT public data fields.

    The source mapping is never mutated.  If the ACT CMB-only likelihood is not
    present, this is a recorded no-op.
    """
    runtime = copy.deepcopy(dict(info))
    likelihoods = runtime.get("likelihood") or {}
    if not isinstance(likelihoods, MutableMapping):
        raise RuntimeError("Likelihood block is not a mapping")

    act_config = likelihoods.get(ACT_LIKELIHOOD_NAME)
    if act_config is None:
        return runtime, {
            "act_likelihood_present": False,
            "source_info_modified": False,
        }
    if not isinstance(act_config, MutableMapping):
        raise RuntimeError(f"{ACT_LIKELIHOOD_NAME} config is not a mapping")

    serialized_version = act_config.get("version")
    serialized_input_file = act_config.get("input_file")
    if serialized_version not in ALLOWED_SERIALIZED_ACT_VERSIONS:
        raise RuntimeError(
            f"Unexpected serialized ACT data version: {serialized_version!r}"
        )
    if serialized_input_file not in ALLOWED_SERIALIZED_ACT_INPUT_FILES:
        raise RuntimeError(
            f"Unexpected serialized ACT input file: {serialized_input_file!r}"
        )

    act_config["version"] = EXPECTED_ACT_DATA_VERSION
    act_config["input_file"] = EXPECTED_ACT_INPUT_FILE

    data_file = packages_path.resolve() / EXPECTED_ACT_DATA_RELATIVE_PATH
    if not data_file.is_file():
        raise RuntimeError(f"Missing pinned ACT DR6 data file: {data_file}")

    return runtime, {
        "act_likelihood_present": True,
        "serialized_version": serialized_version,
        "serialized_input_file": serialized_input_file,
        "runtime_version": EXPECTED_ACT_DATA_VERSION,
        "runtime_input_file": EXPECTED_ACT_INPUT_FILE,
        "data_file": str(data_file),
        "data_file_sha256": sha256_file(data_file),
        "source_info_modified": False,
    }


def prepare_locked_runtime(
    info: Mapping[str, Any],
    packages_path: Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Run all target-blind software gates and prepare an in-memory config."""
    packages = verify_package_versions()
    act_installation = verify_act_lite_installation()
    camb_cosmorec = verify_camb_cosmorec_capability()
    taurend = install_cobaya_taurend_capability_shim()
    runtime, act_normalization = normalize_act_runtime_info(info, packages_path)
    runtime["packages_path"] = str(packages_path.resolve())
    runtime.pop("version", None)
    return runtime, {
        "packages": packages,
        "act_installation": act_installation,
        "camb_cosmorec": camb_cosmorec,
        "taurend_capability": taurend,
        "act_runtime_normalization": act_normalization,
        "target_statistic_computed": False,
    }


def verify_thread_environment(omp_threads: int) -> dict[str, Any]:
    """Require the intended CAMB OpenMP and single-threaded helper libraries."""
    if omp_threads not in {1, 2}:
        raise RuntimeError(f"Unsupported OMP thread count: {omp_threads}")
    expected = {
        "OMP_NUM_THREADS": str(omp_threads),
        "OPENBLAS_NUM_THREADS": "1",
        "MKL_NUM_THREADS": "1",
        "NUMEXPR_NUM_THREADS": "1",
        "OMP_PROC_BIND": "close",
        "OMP_PLACES": "cores",
    }
    actual = {key: os.environ.get(key) for key in expected}
    checks = {key: actual[key] == value for key, value in expected.items()}
    if not all(checks.values()):
        raise RuntimeError(
            f"Thread-environment gate failed: expected={expected}, actual={actual}"
        )
    return {"expected": expected, "actual": actual, "checks": checks}
