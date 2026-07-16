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
from importlib.metadata import version
from pathlib import Path
from typing import Any

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

EXPECTED_LIKELIHOODS = {
    "planck_2018_lowl.TT",
    "planck_2018_lowl.EE_sroll2",
    "act_dr6_cmbonly.PlanckActCut",
    "act_dr6_cmbonly.ACTDR6CMBonly",
}

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

    header, final_row, row_number = read_header_and_last_row(POINT_CHAIN)
    row = dict(zip(header, final_row, strict=True))

    info: dict[str, Any] = yaml_load_file(str(UPDATED_YAML))
    info["packages_path"] = str(packages_path)
    info["output"] = None
    info["timing"] = True
    for key in ("sampler", "resume", "force", "debug", "test"):
        info.pop(key, None)

    declared_likelihoods = set((info.get("likelihood") or {}).keys())
    if declared_likelihoods != EXPECTED_LIKELIHOODS:
        raise RuntimeError(
            "Locked combined YAML likelihood set mismatch: "
            f"declared={sorted(declared_likelihoods)}, "
            f"expected={sorted(EXPECTED_LIKELIHOODS)}"
        )

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
        "combined_yaml_has_exact_locked_likelihoods": (
            declared_likelihoods == EXPECTED_LIKELIHOODS
        ),
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
        "Planck+ACT-lite model.",
        "",
        "No sampler was created, no MPI or MCMC process was started, no target "
        "statistic was computed, and no numerical parameter, likelihood, "
        "posterior, or derived values were recorded.",
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
