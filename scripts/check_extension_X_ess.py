#!/usr/bin/env python3
"""Post-segment, target-blind convergence gate for the derived quantity X.

This program reads one four-chain Cobaya resume workspace, verifies that every
numbered chain is an append-only extension of the corresponding released seed,
computes X = H0*t0*sqrt(Omega_Lambda,0) with direct CAMB 1.5.0 background calls,
and evaluates only technical convergence diagnostics.

It does not run or resume MCMC. It does not calculate a target residual,
posterior location, sign probability, tension, predictive score, evidence, or
scientific verdict. No per-sample X values or posterior summaries are written.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import platform
import re
import subprocess
import sys
import time
import tomllib
from datetime import datetime, timezone
from importlib.metadata import version
from pathlib import Path
from typing import Any

# Keep the diagnostic transform serial and deterministic. These variables must
# be set before importing NumPy/CAMB and their numerical backends.
os.environ["OMP_NUM_THREADS"] = "1"
os.environ["OPENBLAS_NUM_THREADS"] = "1"
os.environ["MKL_NUM_THREADS"] = "1"
os.environ["NUMEXPR_NUM_THREADS"] = "1"

import arviz as az
import camb
import numpy as np
from getdist import chains as getdist_chains
from getdist.mcsamples import MCSamples


EXPECTED_VERSIONS = {
    "cobaya": "3.5.4",
    "camb": "1.5.0",
    "getdist": "1.7.7",
    "arviz": "0.23.4",
    "mpi4py": "4.1.2",
}
EXPECTED_BRANCH = "confirmatory-analysis"
EXPECTED_CHAIN_COUNT = 4
INTEGER_WEIGHT_TOLERANCE = 1e-12
MAX_EXPANDED_DRAWS_PER_CHAIN = 10_000_000
MAX_CLOSURE_ERROR = 1e-10
PROGRESS_EVERY = 25_000

CHAIN_LOCK = Path("config/chain_ingestion_lock.toml")
SEED_MAP = Path("results/provenance/mcmc_extension_seed_map.json")
DEFAULT_OUTPUT_ROOT = Path(
    "results/provenance/mcmc_extension_X_ess"
)
DATASET_CHOICES = (
    "actlite_lcdm_camb",
    "p-actlite_lcdm_camb",
    "planck_lcdm_camb",
)
FORBIDDEN_OUTPUT_TOKENS = (
    "delta_Phi",
    "probability_X_above",
    "probability_X_below",
    "posterior_summary",
    "scientific_verdict",
)


def run_git(args: list[str], root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=root,
        text=True,
        capture_output=True,
        check=False,
    )


def repository_root() -> Path:
    completed = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError("Run this script from inside the Git repository")
    return Path(completed.stdout.strip()).resolve()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def file_is_prefix(prefix_path: Path, extended_path: Path) -> bool:
    """Return True only if extended_path starts byte-for-byte with prefix_path."""
    if extended_path.stat().st_size < prefix_path.stat().st_size:
        return False
    with prefix_path.open("rb") as prefix, extended_path.open("rb") as extended:
        while chunk := prefix.read(1024 * 1024):
            if extended.read(len(chunk)) != chunk:
                return False
    return True


def count_data_rows(path: Path) -> int:
    count = 0
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            stripped = line.strip()
            if stripped and not stripped.startswith("#"):
                count += 1
    return count


def read_header(path: Path) -> list[str]:
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.startswith("#"):
                return line.lstrip("#").split()
            if line.strip():
                break
    raise RuntimeError(f"No header found in {path}")


def load_retained_chain(path: Path, burn_fraction: float) -> dict[str, Any]:
    columns = read_header(path)
    index = {name: position for position, name in enumerate(columns)}
    required = ("weight", "minuslogpost", "H0", "ombh2", "omch2", "tau")
    missing = [name for name in required if name not in index]
    if missing:
        raise RuntimeError(f"{path}: missing required columns {missing}")

    use_names = list(required)
    usecols = [index[name] for name in use_names]
    data = np.loadtxt(
        path,
        comments="#",
        dtype=np.float64,
        usecols=usecols,
    )
    if data.ndim == 1:
        data = data.reshape(1, -1)
    if data.shape[0] == 0:
        raise RuntimeError(f"{path}: chain has no data rows")

    original_rows = int(data.shape[0])
    removed_rows = int(round(original_rows * burn_fraction))
    retained = data[removed_rows:, :]
    if retained.shape[0] == 0:
        raise RuntimeError(f"{path}: burn-in removed all rows")
    if not np.all(np.isfinite(retained)):
        raise RuntimeError(f"{path}: retained data contain non-finite values")

    local = {name: position for position, name in enumerate(use_names)}
    weights = retained[:, local["weight"]]
    if not np.all(weights > 0):
        raise RuntimeError(f"{path}: retained weights are not all positive")

    rounded = np.rint(weights)
    integer_error = float(np.max(np.abs(weights - rounded)))
    if integer_error > INTEGER_WEIGHT_TOLERANCE:
        raise RuntimeError(
            f"{path}: non-integer weights; maximum error {integer_error}"
        )

    return {
        "path": path,
        "original_rows": original_rows,
        "removed_rows": removed_rows,
        "retained_rows": int(retained.shape[0]),
        "weights": weights,
        "integer_weights": rounded.astype(np.int64),
        "minuslogpost": retained[:, local["minuslogpost"]],
        "H0": retained[:, local["H0"]],
        "ombh2": retained[:, local["ombh2"]],
        "omch2": retained[:, local["omch2"]],
        "tau": retained[:, local["tau"]],
        "integer_error": integer_error,
    }


def evaluate_x(
    H0: float,
    ombh2: float,
    omch2: float,
    tau: float,
    config: dict[str, Any],
) -> tuple[float, float, float, float]:
    fixed = config["background"]["fixed_model"]
    units = config["dimensionless_age"]

    pars = camb.CAMBparams()
    pars.set_cosmology(
        H0=float(H0),
        ombh2=float(ombh2),
        omch2=float(omch2),
        omk=float(fixed["omk"]),
        mnu=float(fixed["mnu_eV"]),
        nnu=float(fixed["nnu"]),
        num_massive_neutrinos=int(fixed["num_massive_neutrinos"]),
        neutrino_hierarchy=str(fixed["neutrino_hierarchy"]),
        TCMB=float(fixed["TCMB_K"]),
        tau=float(tau),
    )
    pars.set_dark_energy(w=-1.0, wa=0.0, dark_energy_model="fluid")
    background = camb.get_background(pars, no_thermo=True)

    age = float(background.physical_time(0.0))
    omega_lambda = float(background.get_Omega("de", 0.0))
    omega_m = (
        float(background.get_Omega("baryon", 0.0))
        + float(background.get_Omega("cdm", 0.0))
        + float(background.get_Omega("nu", 0.0))
    )
    closure = (
        omega_m
        + omega_lambda
        + float(background.get_Omega("photon", 0.0))
        + float(background.get_Omega("neutrino", 0.0))
        + float(background.get_Omega("K", 0.0))
    )
    h0t0 = (
        float(H0)
        * 1000.0
        / float(units["Mpc_in_metres"])
        * age
        * float(units["Gyr_in_seconds"])
    )
    x_value = h0t0 * math.sqrt(omega_lambda)
    return x_value, closure, age, omega_lambda


def transform_retained_chain(
    chain: dict[str, Any],
    config: dict[str, Any],
    label: str,
) -> dict[str, Any]:
    rows = chain["retained_rows"]
    x_values = np.empty(rows, dtype=np.float64)
    closures = np.empty(rows, dtype=np.float64)
    ages = np.empty(rows, dtype=np.float64)
    omega_lambdas = np.empty(rows, dtype=np.float64)

    started = time.perf_counter()
    for row in range(rows):
        (
            x_values[row],
            closures[row],
            ages[row],
            omega_lambdas[row],
        ) = evaluate_x(
            chain["H0"][row],
            chain["ombh2"][row],
            chain["omch2"][row],
            chain["tau"][row],
            config,
        )
        if (row + 1) % PROGRESS_EVERY == 0:
            print(f"{label}: {row + 1}/{rows} retained rows", flush=True)

    result = dict(chain)
    result.update(
        {
            "X": x_values,
            "closure": closures,
            "age_Gyr": ages,
            "Omega_Lambda": omega_lambdas,
            "transform_seconds": time.perf_counter() - started,
        }
    )
    return result


def scalar_x_diagnostics(
    chains: list[dict[str, Any]],
    config: dict[str, Any],
) -> dict[str, Any]:
    xs = [chain["X"] for chain in chains]
    weights = [chain["weights"] for chain in chains]
    integer_weights = [chain["integer_weights"] for chain in chains]
    loglikes = [chain["minuslogpost"] for chain in chains]

    getdist_chains.print_load_details = False
    samples = MCSamples(
        samples=[values[:, None] for values in xs],
        weights=weights,
        loglikes=loglikes,
        names=["X"],
        labels=["X"],
        sampler="mcmc",
        ignore_rows=0,
    )
    rminus1 = float(samples.getGelmanRubin())

    expanded: list[np.ndarray] = []
    expanded_lengths: list[int] = []
    for values, multiplicity in zip(xs, integer_weights, strict=True):
        expanded_count = int(multiplicity.sum())
        if expanded_count > MAX_EXPANDED_DRAWS_PER_CHAIN:
            raise RuntimeError(
                "Expanded diagnostic chain exceeds the frozen safety cap: "
                f"{expanded_count} > {MAX_EXPANDED_DRAWS_PER_CHAIN}"
            )
        reconstructed = np.repeat(values, multiplicity)
        expanded.append(reconstructed)
        expanded_lengths.append(int(reconstructed.shape[0]))

    aligned_draws = min(expanded_lengths)
    aligned = np.stack(
        [values[-aligned_draws:] for values in expanded],
        axis=0,
    )
    inference = az.from_dict(posterior={"X": aligned})
    rank_rhat = float(np.asarray(az.rhat(inference, method="rank")["X"]).squeeze())
    bulk_ess = float(np.asarray(az.ess(inference, method="bulk")["X"]).squeeze())
    tail_ess = float(np.asarray(az.ess(inference, method="tail")["X"]).squeeze())

    total_weight = sum(float(value.sum()) for value in weights)
    total_weight_squared = sum(float(np.square(value).sum()) for value in weights)
    retained_weight_ess = total_weight**2 / total_weight_squared

    thresholds = config["convergence"]
    checks = {
        "getdist_R_minus_1_X": (
            math.isfinite(rminus1)
            and rminus1
            <= float(thresholds["weighted_multivariate_R_minus_1_max"])
        ),
        "rank_normalized_split_Rhat_X": (
            math.isfinite(rank_rhat)
            and rank_rhat
            <= float(thresholds["rank_normalized_split_rhat_max"])
        ),
        "bulk_ESS_X": (
            math.isfinite(bulk_ess)
            and bulk_ess
            >= float(thresholds["bulk_ess_minimum_derived_X"])
        ),
        "tail_ESS_X": (
            math.isfinite(tail_ess)
            and tail_ess
            >= float(thresholds["tail_ess_minimum_derived_X"])
        ),
        "minimum_retained_weight_ESS": (
            retained_weight_ess
            >= float(thresholds["minimum_retained_weight_ess"])
        ),
    }

    return {
        "getdist_R_minus_1_X": rminus1,
        "rank_Rhat_X": rank_rhat,
        "bulk_ESS_X": bulk_ess,
        "tail_ESS_X": tail_ess,
        "retained_weight_ESS": retained_weight_ess,
        "expanded_draw_lengths": expanded_lengths,
        "aligned_draws_per_chain": aligned_draws,
        "thresholds": {
            "getdist_R_minus_1_max": float(
                thresholds["weighted_multivariate_R_minus_1_max"]
            ),
            "rank_Rhat_max": float(
                thresholds["rank_normalized_split_rhat_max"]
            ),
            "bulk_ESS_X_min": float(
                thresholds["bulk_ess_minimum_derived_X"]
            ),
            "tail_ESS_X_min": float(
                thresholds["tail_ess_minimum_derived_X"]
            ),
            "retained_weight_ESS_min": float(
                thresholds["minimum_retained_weight_ess"]
            ),
        },
        "checks": checks,
        "pass": all(checks.values()),
    }


def technical_validation(chains: list[dict[str, Any]]) -> dict[str, Any]:
    closures = np.concatenate([chain["closure"] for chain in chains])
    ages = np.concatenate([chain["age_Gyr"] for chain in chains])
    omega_lambdas = np.concatenate([chain["Omega_Lambda"] for chain in chains])
    maximum_closure_error = float(np.max(np.abs(closures - 1.0)))
    checks = {
        "finite_derived_values": bool(
            np.all(np.isfinite(closures))
            and np.all(np.isfinite(ages))
            and np.all(np.isfinite(omega_lambdas))
        ),
        "closure": maximum_closure_error <= MAX_CLOSURE_ERROR,
        "positive_age": bool(np.all(ages > 0)),
        "physical_Omega_Lambda": bool(
            np.all((omega_lambdas > 0) & (omega_lambdas < 1))
        ),
    }
    return {
        "maximum_closure_error": maximum_closure_error,
        "maximum_allowed_closure_error": MAX_CLOSURE_ERROR,
        "checks": checks,
        "pass": all(checks.values()),
    }


def find_seed_mapping(
    record: dict[str, Any],
    destination_relative: str,
) -> dict[str, Any]:
    matches = [
        item
        for item in record["copied_files"]
        if item["destination"] == destination_relative
    ]
    if len(matches) != 1:
        raise RuntimeError(
            f"Expected one seed-map entry for {destination_relative}; "
            f"found {len(matches)}"
        )
    return matches[0]


def output_path(root: Path, dataset: str, segment_label: str) -> Path:
    return root / dataset / segment_label


def write_json_safely(path: Path, payload: dict[str, Any]) -> None:
    encoded = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    for token in FORBIDDEN_OUTPUT_TOKENS:
        if token in encoded:
            raise RuntimeError(f"Refusing output containing forbidden token: {token}")
    path.write_text(encoded, encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Compute target-blind derived-X convergence diagnostics after one "
            "MCMC extension segment. This does not start or resume MCMC."
        )
    )
    parser.add_argument("--dataset", required=True, choices=DATASET_CHOICES)
    parser.add_argument(
        "--segment-label",
        required=True,
        help="Unique immutable label, for example segment-001.",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=DEFAULT_OUTPUT_ROOT,
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", args.segment_label):
        raise SystemExit("Invalid --segment-label")

    root = repository_root()
    os.chdir(root)
    out = output_path(args.output_root, args.dataset, args.segment_label)
    if out.exists():
        raise SystemExit(f"{out} already exists; refusing to overwrite")

    branch = run_git(["branch", "--show-current"], root).stdout.strip()
    head = run_git(["rev-parse", "HEAD"], root).stdout.strip()
    tracked_status = run_git(
        ["status", "--porcelain", "--untracked-files=no"], root
    ).stdout.strip()
    if branch != EXPECTED_BRANCH:
        raise SystemExit(f"Wrong branch: {branch!r}")
    if tracked_status:
        raise SystemExit("Tracked working tree is not clean")

    out.mkdir(parents=True)
    started = time.perf_counter()

    try:
        installed_versions = {name: version(name) for name in EXPECTED_VERSIONS}
        version_checks = {
            name: installed_versions[name] == expected
            for name, expected in EXPECTED_VERSIONS.items()
        }
        if not all(version_checks.values()):
            raise RuntimeError(
                f"Software version mismatch: {installed_versions}"
            )

        with CHAIN_LOCK.open("rb") as handle:
            config = tomllib.load(handle)
        seed_map = json.loads(SEED_MAP.read_text(encoding="utf-8"))
        record = seed_map[args.dataset]
        chain_dir = (root / record["destination_directory"]).resolve()
        prefix = str(record["output_prefix"])
        burn_fraction = float(
            config["ingestion"]["primary_ignore_rows_fraction"]
        )

        paths = [chain_dir / f"{prefix}.{number}.txt" for number in range(1, 5)]
        missing = [str(path) for path in paths if not path.is_file()]
        if missing:
            raise RuntimeError(f"Missing numbered chain files: {missing}")

        numbered_pattern = re.compile(
            rf"^{re.escape(prefix)}\.(\d+)\.txt$"
        )
        numbered_candidates = sorted(
            int(match.group(1))
            for path in chain_dir.glob(f"{prefix}.*.txt")
            if (match := numbered_pattern.fullmatch(path.name))
        )
        if numbered_candidates != [1, 2, 3, 4]:
            raise RuntimeError(
                "Expected exactly numbered chains 1--4; found "
                f"{numbered_candidates}"
            )

        integrity_records: list[dict[str, Any]] = []
        checksum_lines: list[str] = []
        for number, current in enumerate(paths, 1):
            destination_relative = current.relative_to(root).as_posix()
            mapping = find_seed_mapping(record, destination_relative)
            source = (root / mapping["source"]).resolve()
            if not source.is_file():
                raise RuntimeError(f"Missing original released chain: {source}")

            source_hash = sha256_file(source)
            current_hash = sha256_file(current)
            source_rows = count_data_rows(source)
            current_rows = count_data_rows(current)
            prefix_match = file_is_prefix(source, current)
            integrity_records.append(
                {
                    "chain_number": number,
                    "source": source.relative_to(root).as_posix(),
                    "current": current.relative_to(root).as_posix(),
                    "source_sha256": source_hash,
                    "seed_map_source_sha256": mapping["source_sha256"],
                    "current_sha256": current_hash,
                    "source_rows": source_rows,
                    "current_rows": current_rows,
                    "appended_rows": current_rows - source_rows,
                    "source_hash_matches_seed_map": (
                        source_hash == mapping["source_sha256"]
                    ),
                    "current_is_append_only_extension": prefix_match,
                    "chain_grew": current_rows > source_rows,
                }
            )
            checksum_lines.append(
                f"{current_hash}  {current.relative_to(root).as_posix()}"
            )

        integrity_checks = {
            "exactly_four_numbered_chains": len(paths) == EXPECTED_CHAIN_COUNT,
            "all_source_hashes_match_seed_map": all(
                item["source_hash_matches_seed_map"] for item in integrity_records
            ),
            "all_current_chains_are_append_only_extensions": all(
                item["current_is_append_only_extension"] for item in integrity_records
            ),
            "all_four_chains_grew": all(
                item["chain_grew"] for item in integrity_records
            ),
        }
        if not all(integrity_checks.values()):
            raise RuntimeError(f"Chain integrity gate failed: {integrity_checks}")

        loaded = [
            load_retained_chain(path, burn_fraction)
            for path in paths
        ]
        transformed = [
            transform_retained_chain(
                chain,
                config,
                f"{prefix}.{number}",
            )
            for number, chain in enumerate(loaded, 1)
        ]

        ending_hashes = [sha256_file(path) for path in paths]
        files_unchanged_during_diagnostic = all(
            item["current_sha256"] == ending_hash
            for item, ending_hash in zip(
                integrity_records, ending_hashes, strict=True
            )
        )
        integrity_checks[
            "chain_files_unchanged_during_diagnostic"
        ] = files_unchanged_during_diagnostic
        if not files_unchanged_during_diagnostic:
            raise RuntimeError(
                "One or more chain files changed while diagnostics were running; "
                "stop the MCMC segment before rerunning this checker"
            )

        validation = technical_validation(transformed)
        diagnostics = scalar_x_diagnostics(transformed, config)
        overall_pass = validation["pass"] and diagnostics["pass"]

        report = {
            "phase": "post-segment derived-X technical convergence gate",
            "created_utc": datetime.now(timezone.utc).isoformat(),
            "dataset": args.dataset,
            "segment_label": args.segment_label,
            "repository": {
                "root": str(root),
                "branch": branch,
                "commit": head,
                "tracked_worktree_clean_before_output": not tracked_status,
            },
            "software": {
                "python": platform.python_version(),
                **installed_versions,
            },
            "thread_environment": {
                name: os.environ.get(name)
                for name in (
                    "OMP_NUM_THREADS",
                    "OPENBLAS_NUM_THREADS",
                    "MKL_NUM_THREADS",
                    "NUMEXPR_NUM_THREADS",
                )
            },
            "inputs": {
                "chain_ingestion_lock": str(CHAIN_LOCK),
                "chain_ingestion_lock_sha256": sha256_file(CHAIN_LOCK),
                "seed_map": str(SEED_MAP),
                "seed_map_sha256": sha256_file(SEED_MAP),
                "chain_directory": chain_dir.relative_to(root).as_posix(),
                "output_prefix": prefix,
                "primary_burn_fraction": burn_fraction,
            },
            "chain_integrity": {
                "chains": integrity_records,
                "checks": integrity_checks,
                "pass": all(integrity_checks.values()),
            },
            "retained_chain_rows": [
                {
                    "chain_number": number,
                    "original_rows": chain["original_rows"],
                    "removed_rows": chain["removed_rows"],
                    "retained_rows": chain["retained_rows"],
                    "maximum_integer_weight_error": chain["integer_error"],
                    "transform_seconds": chain["transform_seconds"],
                }
                for number, chain in enumerate(transformed, 1)
            ],
            "technical_validation": validation,
            "derived_X_convergence": diagnostics,
            "checks": {
                "software_versions": all(version_checks.values()),
                "chain_integrity": all(integrity_checks.values()),
                "technical_validation": validation["pass"],
                "derived_X_convergence": diagnostics["pass"],
                "no_target_comparison_performed": True,
                "no_posterior_location_summary_written": True,
                "no_per_sample_X_values_written": True,
                "no_MCMC_started_by_this_script": True,
            },
            "overall_pass": overall_pass,
            "wall_seconds": time.perf_counter() - started,
            "disclosure_boundary": (
                "Technical convergence diagnostics only. No posterior location, "
                "target comparison, predictive calculation, evidence calculation, "
                "or scientific verdict is present."
            ),
        }
        report["checks"]["all_checks"] = all(report["checks"].values())
        report["overall_pass"] = report["overall_pass"] and report["checks"]["all_checks"]

        (out / "chain-checksums.txt").write_text(
            "\n".join(checksum_lines) + "\n",
            encoding="utf-8",
        )
        write_json_safely(out / "diagnostics.json", report)

        print(f"Overall: {'PASS' if report['overall_pass'] else 'FAIL'}")
        print(f"Dataset: {args.dataset}")
        print(f"Segment: {args.segment_label}")
        print(f"GetDist R-1(X): {diagnostics['getdist_R_minus_1_X']}")
        print(f"Rank R-hat(X): {diagnostics['rank_Rhat_X']}")
        print(f"Bulk ESS(X): {diagnostics['bulk_ESS_X']}")
        print(f"Tail ESS(X): {diagnostics['tail_ESS_X']}")
        print(f"Output: {out}")
        return 0 if report["overall_pass"] else 1

    except Exception as exc:
        failure = {
            "phase": "post-segment derived-X technical convergence gate",
            "created_utc": datetime.now(timezone.utc).isoformat(),
            "dataset": args.dataset,
            "segment_label": args.segment_label,
            "repository_commit": head,
            "error_type": type(exc).__name__,
            "error": str(exc),
            "overall_pass": False,
            "no_target_comparison_performed": True,
            "no_posterior_location_summary_written": True,
            "no_per_sample_X_values_written": True,
            "no_MCMC_started_by_this_script": True,
        }
        write_json_safely(out / "technical_failure.json", failure)
        print(f"ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        print(f"Technical failure output: {out / 'technical_failure.json'}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
