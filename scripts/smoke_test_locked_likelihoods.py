#!/usr/bin/env python3
"""
Run one target-blind, finite Cobaya likelihood smoke evaluation.

The script:
- uses the locked Planck+ACT-lite updated YAML;
- reads one existing released-chain point;
- initializes CAMB and all four locked CMB likelihood components;
- performs exactly one serial posterior evaluation;
- records only technical pass/fail information, names, hashes, and timing.

It does not create a sampler, start or resume MCMC, compute X, inspect the
golden-ratio target, or record numerical posterior/likelihood/derived values.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import platform
import subprocess
import sys
import time
from importlib.metadata import distribution, version
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")
os.environ.setdefault("NUMEXPR_NUM_THREADS", "1")

import numpy as np
from cobaya.model import get_model
from cobaya.yaml import yaml_load_file


EXPECTED_VERSIONS = {
    "cobaya": "3.5.4",
    "camb": "1.5.0",
    "getdist": "1.7.7",
    "arviz": "0.23.4",
    "mpi4py": "4.1.2",
}

EXPECTED_CAMB_COMMIT = "28e4036519155531f4ed9a4e1d8afb1579d2de11"
EXPECTED_CAMB_SOURCE = Path("/opt/cosmology-software/CAMB-1.5.0-cosmorec")

EXPECTED_LIKELIHOODS = {
    "planck_2018_lowl.TT",
    "planck_2018_lowl.EE_sroll2",
    "act_dr6_cmbonly.PlanckActCut",
    "act_dr6_cmbonly.ACTDR6CMBonly",
}

ACT_LIKELIHOOD_NAME = "act_dr6_cmbonly.ACTDR6CMBonly"
EXPECTED_ACT_DATA_VERSION = "v1.0"
EXPECTED_ACT_DATA_RELATIVE_PATH = Path(
    "data/ACTDR6CMBonly/v1.0/dr6_data_cmbonly.fits"
)

REPO_ROOT = Path(
    subprocess.check_output(
        ["git", "rev-parse", "--show-toplevel"],
        text=True,
    ).strip()
)

MODEL_DIR = (
    REPO_ROOT
    / "data/derived/act_dr6_02/mcmc_extension_seed/p-actlite_lcdm_camb"
)
UPDATED_YAML = MODEL_DIR / "p-act-camb-lcdm.updated.yaml"
POINT_CHAIN = MODEL_DIR / "p-act-camb-lcdm.1.txt"

INSTALL_REPORT = (
    REPO_ROOT
    / "results/provenance/locked_likelihood_data_installation/verification.json"
)

OUTPUT_DIR = (
    REPO_ROOT
    / "results/provenance/locked_likelihood_smoke_test"
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def git(*args: str) -> str:
    return subprocess.check_output(
        ["git", *args],
        cwd=REPO_ROOT,
        text=True,
    ).strip()


def verify_camb_cosmorec_capability() -> dict[str, Any]:
    """Reject a stock CAMB wheel before any model initialization."""
    import camb

    expected_source = Path(
        os.environ.get("CAMB_COSMOREC_SOURCE_DIR", str(EXPECTED_CAMB_SOURCE))
    ).resolve()
    if not expected_source.is_dir():
        raise RuntimeError(
            f"Pinned CAMB CosmoRec source directory is missing: {expected_source}"
        )

    module_path = Path(camb.__file__).resolve()
    params = camb.CAMBparams()
    params.set_classes(recombination_model="CosmoRec")

    raw = distribution("camb").read_text("direct_url.json")
    if raw is None:
        raise RuntimeError(
            "CAMB has no direct_url.json; a stock or untracked installation "
            "cannot pass the CosmoRec gate"
        )
    direct_url = json.loads(raw)
    parsed = urlparse(str(direct_url.get("url", "")))
    source_path = (
        Path(unquote(parsed.path)).resolve()
        if parsed.scheme == "file"
        else None
    )
    editable = bool(direct_url.get("dir_info", {}).get("editable"))

    commit_result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=expected_source,
        text=True,
        capture_output=True,
    )
    installed_commit = (
        commit_result.stdout.strip() if commit_result.returncode == 0 else ""
    )

    camblib = expected_source / "camb/camblib.so"
    ldd_result = subprocess.run(
        ["ldd", str(camblib)],
        text=True,
        capture_output=True,
    ) if camblib.is_file() else None
    libraries_resolved = bool(
        ldd_result
        and ldd_result.returncode == 0
        and "not found" not in ldd_result.stdout
        and "not found" not in ldd_result.stderr
    )

    checks = {
        "metadata_version_1_5_0": version("camb") == "1.5.0",
        "module_version_1_5_0": camb.__version__ == "1.5.0",
        "module_inside_pinned_source": module_path.is_relative_to(expected_source),
        "editable_source_path_matches": (
            editable and source_path == expected_source
        ),
        "source_commit_matches": installed_commit == EXPECTED_CAMB_COMMIT,
        "cosmorec_class_available": (
            type(params.Recomb).__name__ == "CosmoRec"
        ),
        "camblib_exists": camblib.is_file(),
        "linked_libraries_resolved": libraries_resolved,
    }
    if not all(checks.values()):
        raise RuntimeError(f"CAMB CosmoRec capability gate failed: {checks}")

    return {
        "expected_source": str(expected_source),
        "module_path": str(module_path),
        "expected_commit": EXPECTED_CAMB_COMMIT,
        "installed_commit": installed_commit,
        "recombination_class": type(params.Recomb).__name__,
        "direct_url": direct_url,
        "camblib_sha256": sha256(camblib),
        "checks": checks,
        "numerical_spectra_computed": False,
    }


def read_header_and_last_row(path: Path) -> tuple[list[str], list[float], int]:
    header: list[str] | None = None
    last_values: list[float] | None = None
    last_row_number = 0
    data_row_number = 0

    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            stripped = line.strip()
            if not stripped:
                continue
            if stripped.startswith("#"):
                if header is None:
                    header = stripped.lstrip("#").split()
                continue

            data_row_number += 1
            fields = stripped.split()
            try:
                values = [float(value) for value in fields]
            except ValueError as exc:
                raise RuntimeError(
                    f"{path}: non-numeric data row {data_row_number}"
                ) from exc

            last_values = values
            last_row_number = data_row_number

    if header is None:
        raise RuntimeError(f"{path}: no header line found")
    if last_values is None:
        raise RuntimeError(f"{path}: no data rows found")
    if len(last_values) != len(header):
        raise RuntimeError(
            f"{path}: header has {len(header)} columns but final row has "
            f"{len(last_values)}"
        )
    if not all(math.isfinite(value) for value in last_values):
        raise RuntimeError(f"{path}: final row contains non-finite values")

    return header, last_values, last_row_number


def safe_mkdir(path: Path) -> None:
    if path.exists():
        raise RuntimeError(
            f"{path} already exists; refusing to overwrite a prior smoke test"
        )
    path.mkdir(parents=True)


def main() -> int:
    started_utc = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    wall_start = time.perf_counter()

    tracked_status = git("status", "--porcelain", "--untracked-files=no")
    if tracked_status:
        raise RuntimeError(
            "Tracked working tree is not clean before smoke evaluation:\n"
            + tracked_status
        )

    if not UPDATED_YAML.is_file():
        raise RuntimeError(f"Missing locked updated YAML: {UPDATED_YAML}")
    if not POINT_CHAIN.is_file():
        raise RuntimeError(f"Missing source chain: {POINT_CHAIN}")
    if not INSTALL_REPORT.is_file():
        raise RuntimeError(f"Missing installation report: {INSTALL_REPORT}")

    install_report = json.loads(
        INSTALL_REPORT.read_text(encoding="utf-8")
    )
    if install_report.get("overall_pass") is not True:
        raise RuntimeError("Locked likelihood-data installation did not pass")

    packages_path = Path(
        os.environ.get("COBAYA_PACKAGES_PATH", "")
    ).expanduser().resolve()
    if not str(packages_path):
        raise RuntimeError("COBAYA_PACKAGES_PATH is not set")
    if not packages_path.is_dir():
        raise RuntimeError(
            f"COBAYA_PACKAGES_PATH does not exist: {packages_path}"
        )
    if str(packages_path) != install_report.get("packages_path"):
        raise RuntimeError(
            "COBAYA_PACKAGES_PATH differs from the locked installation report"
        )

    installed_versions = {
        package: version(package)
        for package in EXPECTED_VERSIONS
    }
    version_checks = {
        package: installed_versions[package] == expected
        for package, expected in EXPECTED_VERSIONS.items()
    }
    if not all(version_checks.values()):
        raise RuntimeError(
            f"Version mismatch: {version_checks}; installed={installed_versions}"
        )

    camb_cosmorec = verify_camb_cosmorec_capability()

    header, final_row, row_number = read_header_and_last_row(POINT_CHAIN)
    row = dict(zip(header, final_row, strict=True))

    info: dict[str, Any] = yaml_load_file(str(UPDATED_YAML))
    info["packages_path"] = str(packages_path)
    info["output"] = None
    info["timing"] = True
    for key in ("sampler", "resume", "force", "debug", "test"):
        info.pop(key, None)

    likelihood_info = info.get("likelihood") or {}
    declared_likelihoods = set(likelihood_info.keys())
    if declared_likelihoods != EXPECTED_LIKELIHOODS:
        raise RuntimeError(
            "Locked combined YAML likelihood set mismatch: "
            f"declared={sorted(declared_likelihoods)}, "
            f"expected={sorted(EXPECTED_LIKELIHOODS)}"
        )

    act_config = likelihood_info.get(ACT_LIKELIHOOD_NAME)
    if not isinstance(act_config, dict):
        raise RuntimeError(
            f"{ACT_LIKELIHOOD_NAME} configuration is not a dictionary"
        )

    serialized_act_version = act_config.get("version")
    if serialized_act_version not in (None, EXPECTED_ACT_DATA_VERSION):
        raise RuntimeError(
            "Unexpected ACT DR6 data version in locked updated YAML: "
            f"{serialized_act_version!r}"
        )

    # The pinned DR6-ACT-lite class uses ``version`` for its data subdirectory
    # ("v1.0"), while Cobaya's serialized updated YAML can contain
    # ``version: null`` as generic component metadata.  Passing that null value
    # directly overrides the class default and makes initialization attempt
    # os.path.join(..., None, ...). Restore the pinned data version explicitly
    # in this runtime copy only; the source YAML remains untouched and hashed.
    act_config["version"] = EXPECTED_ACT_DATA_VERSION

    act_data_file = packages_path / EXPECTED_ACT_DATA_RELATIVE_PATH
    if not act_data_file.is_file():
        raise RuntimeError(f"Missing locked ACT DR6 data file: {act_data_file}")

    safe_mkdir(OUTPUT_DIR)

    model = None
    result: dict[str, Any] | None = None
    error: str | None = None
    initialization_seconds: float | None = None
    evaluation_seconds: float | None = None
    sampled_names: list[str] = []
    returned_likelihood_names: list[str] = []
    finite_likelihoods: dict[str, bool] = {}
    finite_logposterior = False

    try:
        init_start = time.perf_counter()
        model = get_model(info)
        initialization_seconds = time.perf_counter() - init_start

        sampled_names = list(model.parameterization.sampled_params())
        missing = [name for name in sampled_names if name not in row]
        if missing:
            raise RuntimeError(
                f"Source chain lacks sampled parameters required by model: {missing}"
            )

        point = {name: row[name] for name in sampled_names}

        eval_start = time.perf_counter()
        posterior = model.logposterior(point, as_dict=True)
        evaluation_seconds = time.perf_counter() - eval_start

        loglikes = posterior.get("loglikes", {})
        returned_likelihood_names = sorted(loglikes)
        finite_likelihoods = {
            name: bool(np.isfinite(loglikes.get(name, np.nan)))
            for name in sorted(EXPECTED_LIKELIHOODS)
        }
        finite_logposterior = bool(
            np.isfinite(posterior.get("logpost", np.nan))
        )

        result = {
            "likelihood_name_set_matches": (
                set(loglikes) == EXPECTED_LIKELIHOODS
            ),
            "all_likelihood_values_finite": all(finite_likelihoods.values()),
            "logposterior_finite": finite_logposterior,
        }
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
    finally:
        if model is not None:
            model.close()

    ended_utc = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    total_seconds = time.perf_counter() - wall_start

    checks = {
        "installation_report_passed": True,
        "tracked_worktree_clean_before_run": True,
        "software_versions_match": all(version_checks.values()),
        "camb_cosmorec_capability_passed": all(
            camb_cosmorec["checks"].values()
        ),
        "combined_yaml_has_exact_locked_likelihoods": (
            declared_likelihoods == EXPECTED_LIKELIHOODS
        ),
        "serialized_act_version_is_null_or_v1_0": (
            serialized_act_version in (None, EXPECTED_ACT_DATA_VERSION)
        ),
        "runtime_act_data_version_is_v1_0": (
            act_config.get("version") == EXPECTED_ACT_DATA_VERSION
        ),
        "locked_act_data_file_exists": act_data_file.is_file(),
        "model_initialized": initialization_seconds is not None,
        "one_evaluation_completed": evaluation_seconds is not None,
        "returned_exact_locked_likelihoods": bool(
            result and result["likelihood_name_set_matches"]
        ),
        "all_four_likelihoods_finite": bool(
            result and result["all_likelihood_values_finite"]
        ),
        "finite_logposterior": bool(
            result and result["logposterior_finite"]
        ),
        "no_sampler_created": True,
        "no_mcmc_started": True,
        "no_target_statistic_computed": True,
        "no_numerical_likelihood_values_recorded": True,
        "no_parameter_values_recorded": True,
        "no_derived_values_recorded": True,
    }
    overall_pass = error is None and all(checks.values())

    report = {
        "purpose": "one target-blind finite likelihood smoke evaluation",
        "overall_pass": overall_pass,
        "started_utc": started_utc,
        "ended_utc": ended_utc,
        "repository": {
            "root": str(REPO_ROOT),
            "commit": git("rev-parse", "HEAD"),
            "branch": git("branch", "--show-current"),
        },
        "machine": {
            "hostname": platform.node(),
            "python_executable": sys.executable,
            "python_version": platform.python_version(),
            "logical_cpus": os.cpu_count(),
            "thread_environment": {
                key: os.environ.get(key)
                for key in (
                    "OMP_NUM_THREADS",
                    "OPENBLAS_NUM_THREADS",
                    "MKL_NUM_THREADS",
                    "NUMEXPR_NUM_THREADS",
                )
            },
        },
        "software_versions": installed_versions,
        "software_version_checks": version_checks,
        "camb_cosmorec": camb_cosmorec,
        "inputs": {
            "updated_yaml": str(UPDATED_YAML.relative_to(REPO_ROOT)),
            "updated_yaml_sha256": sha256(UPDATED_YAML),
            "source_chain": str(POINT_CHAIN.relative_to(REPO_ROOT)),
            "source_chain_sha256": sha256(POINT_CHAIN),
            "source_chain_data_row": row_number,
            "sampled_parameter_count": len(sampled_names),
            "parameter_values_recorded": False,
        },
        "likelihoods": {
            "expected_names": sorted(EXPECTED_LIKELIHOODS),
            "declared_names": sorted(declared_likelihoods),
            "returned_names": returned_likelihood_names,
            "finite_by_name": finite_likelihoods,
            "act_data_version": {
                "serialized_updated_yaml_value": serialized_act_version,
                "runtime_value": act_config.get("version"),
                "expected_value": EXPECTED_ACT_DATA_VERSION,
                "source_yaml_modified": False,
            },
            "act_data_file": {
                "path": str(act_data_file),
                "sha256": sha256(act_data_file),
            },
            "numerical_values_recorded": False,
        },
        "timing_seconds": {
            "model_initialization": initialization_seconds,
            "single_evaluation": evaluation_seconds,
            "total_script": total_seconds,
        },
        "checks": checks,
        "error": error,
        "sampler_created": False,
        "mpi_started": False,
        "mcmc_started": False,
        "target_statistic_computed": False,
        "derived_values_recorded": False,
    }

    (OUTPUT_DIR / "verification.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    lines = [
        "# Locked likelihood smoke test",
        "",
        f"Overall status: **{'PASS' if overall_pass else 'FAIL'}**",
        "",
        "Exactly one serial posterior evaluation was requested using the locked "
        "Planck+ACT-lite model. The serialized ACT data-version null value was "
        "normalized in memory to the pinned package data release v1.0; the "
        "source YAML was not modified.",
        "",
        "No sampler was created, no MPI or MCMC process was started, no target "
        "statistic was computed, and no numerical parameter, likelihood, "
        "posterior, or derived values were recorded.",
        "",
        "CAMB 1.5.0 was verified as an editable build from the pinned source "
        "commit with the CosmoRec class available before model initialization.",
        "",
        "## Likelihood components",
        "",
    ]
    for name in sorted(EXPECTED_LIKELIHOODS):
        status = "PASS" if finite_likelihoods.get(name, False) else "FAIL"
        lines.append(f"- `{name}`: **{status}** (finite)")
    lines.extend(
        [
            "",
            "## Timing",
            "",
            f"- Model initialization: `{initialization_seconds}` seconds",
            f"- Single evaluation: `{evaluation_seconds}` seconds",
            f"- Total script: `{total_seconds}` seconds",
            "",
            "## Checks",
            "",
            "```json",
            json.dumps(checks, indent=2, sort_keys=True),
            "```",
        ]
    )
    if error:
        lines.extend(["", "## Error", "", f"`{error}`"])

    (OUTPUT_DIR / "REPORT.md").write_text(
        "\n".join(lines) + "\n",
        encoding="utf-8",
    )

    print(f"Overall: {'PASS' if overall_pass else 'FAIL'}")
    print(f"Output: {OUTPUT_DIR}")
    if error:
        print(f"Error: {error}")
    return 0 if overall_pass else 1


if __name__ == "__main__":
    raise SystemExit(main())
