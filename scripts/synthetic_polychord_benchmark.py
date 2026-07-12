#!/usr/bin/env python3
"""
Synthetic PolyChord/anesthetic execution-lock benchmark.

This benchmark uses no cosmological data. It verifies:
  1. PolyChord evidence estimates against analytic evidences.
  2. Agreement between two independent sampler seeds.
  3. anesthetic.read_chains and anesthetic.tension.tension_stats.
  4. Correct qualitative separation of concordant and shifted data pairs.

Run from the repository root, preferably under MPI:

    mpirun -np 2 python scripts/synthetic_polychord_benchmark.py

Use --overwrite only to deliberately replace an earlier benchmark run.
"""

from __future__ import annotations

import argparse
import json
import math
import shutil
import subprocess
import sys
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Iterable

import numpy as np
from scipy.special import ndtr
from scipy.stats import chi2, norm

import pypolychord
from pypolychord.settings import PolyChordSettings

try:
    from mpi4py import MPI
except ImportError as exc:  # pragma: no cover
    raise SystemExit("mpi4py is required for the execution-lock benchmark") from exc


LOWER = -10.0
UPPER = 10.0
PRIOR_WIDTH = UPPER - LOWER
NDIMS = 1
NDERIVED = 0

# Two independent seeds are part of the frozen execution protocol.
SEEDS = (20260712, 20260713)

# Five likelihood cases: A, concordant B, their joint; shifted B, its joint with A.
CASES: dict[str, tuple[float, ...]] = {
    "A": (0.0,),
    "B_concordant": (0.0,),
    "AB_concordant": (0.0, 0.0),
    "B_shifted": (4.0,),
    "AB_shifted": (0.0, 4.0),
}


@dataclass(frozen=True)
class RunResult:
    case: str
    seed: int
    root: str
    logZ: float
    logZerr: float
    analytic_logZ: float
    absolute_error: float
    analytic_pass: bool


def package_version(name: str) -> str:
    try:
        return version(name)
    except PackageNotFoundError:
        return "not-installed"


def git_commit(path: Path) -> str:
    try:
        return subprocess.check_output(
            ["git", "-C", str(path), "rev-parse", "HEAD"],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return "unavailable"


def analytic_log_evidence(means: Iterable[float]) -> float:
    """
    Exact evidence for a product of unit-normal Gaussian likelihoods
    under a normalized Uniform(LOWER, UPPER) prior.

    Product_i N(theta | mu_i, 1) =
      C * N(theta | mean(mu), 1/sqrt(n)),
    where
      log C = -(n-1)/2 log(2*pi) - 1/2 log(n)
              - 1/2 sum_i (mu_i - mean(mu))^2.
    """
    mus = np.asarray(tuple(means), dtype=float)
    n = mus.size
    if n < 1:
        raise ValueError("At least one Gaussian factor is required")

    mean_mu = float(np.mean(mus))
    within_sum_sq = float(np.sum((mus - mean_mu) ** 2))
    posterior_sigma = 1.0 / math.sqrt(n)

    upper_z = (UPPER - mean_mu) / posterior_sigma
    lower_z = (LOWER - mean_mu) / posterior_sigma
    trunc_mass = float(ndtr(upper_z) - ndtr(lower_z))
    if not (0.0 < trunc_mass <= 1.0):
        raise RuntimeError(f"Invalid truncated Gaussian mass: {trunc_mass}")

    log_c = (
        -0.5 * (n - 1) * math.log(2.0 * math.pi)
        -0.5 * math.log(n)
        -0.5 * within_sum_sq
    )
    return -math.log(PRIOR_WIDTH) + log_c + math.log(trunc_mass)


def make_loglikelihood(means: tuple[float, ...]):
    normalizer = -0.5 * math.log(2.0 * math.pi)

    def loglikelihood(theta):
        x = float(theta[0])
        logl = sum(normalizer - 0.5 * (x - mu) ** 2 for mu in means)
        return float(logl), []

    return loglikelihood


def prior(hypercube):
    u = float(hypercube[0])
    return np.asarray([LOWER + PRIOR_WIDTH * u], dtype=float)


def no_op_dumper(live, dead, logweights, logZ, logZerr):
    del live, dead, logweights, logZ, logZerr


def scalar(value) -> float:
    array = np.asarray(value)
    if array.size != 1:
        raise ValueError(f"Expected scalar output, received shape {array.shape}")
    return float(array.reshape(-1)[0])


def run_case(
    case: str,
    means: tuple[float, ...],
    seed: int,
    raw_dir: Path,
    nlive: int,
    num_repeats: int,
    precision: float,
) -> RunResult | None:
    file_root = f"{case}_seed{seed}"
    root = raw_dir / file_root

    settings = PolyChordSettings(NDIMS, NDERIVED)
    settings.base_dir = str(raw_dir)
    settings.file_root = file_root
    settings.seed = int(seed)
    settings.nlive = int(nlive)
    settings.num_repeats = int(num_repeats)
    settings.precision_criterion = float(precision)
    settings.do_clustering = False
    settings.read_resume = False
    settings.write_resume = True
    settings.write_stats = True
    settings.write_live = True
    settings.write_dead = True
    settings.write_prior = True

    output = pypolychord.run_polychord(
        make_loglikelihood(means),
        NDIMS,
        NDERIVED,
        settings,
        prior,
        no_op_dumper,
    )

    rank = MPI.COMM_WORLD.Get_rank()
    if rank != 0:
        return None

    output.make_paramnames_files([("theta", r"\theta")])

    logz = scalar(output.logZ)
    logzerr = abs(scalar(output.logZerr))
    exact = analytic_log_evidence(means)
    abs_error = abs(logz - exact)

    # Analytic acceptance: at most 0.15 log units or 3 reported standard errors.
    analytic_tolerance = max(0.15, 3.0 * logzerr)
    return RunResult(
        case=case,
        seed=seed,
        root=str(root),
        logZ=logz,
        logZerr=logzerr,
        analytic_logZ=exact,
        absolute_error=abs_error,
        analytic_pass=abs_error <= analytic_tolerance,
    )


def repeat_agreement(results: list[RunResult]) -> dict[str, dict[str, float | bool]]:
    by_case: dict[str, list[RunResult]] = {}
    for result in results:
        by_case.setdefault(result.case, []).append(result)

    checks: dict[str, dict[str, float | bool]] = {}
    for case, case_results in sorted(by_case.items()):
        case_results.sort(key=lambda item: item.seed)
        if len(case_results) != 2:
            raise RuntimeError(f"{case}: expected 2 seeds, found {len(case_results)}")
        first, second = case_results
        difference = abs(first.logZ - second.logZ)
        combined_error = math.hypot(first.logZerr, second.logZerr)
        tolerance = max(0.20, 2.0 * combined_error)
        checks[case] = {
            "absolute_logZ_difference": difference,
            "combined_reported_error": combined_error,
            "tolerance": tolerance,
            "pass": difference <= tolerance,
        }
    return checks


def summarize_distribution(frame, columns: Iterable[str]) -> dict[str, dict[str, float]]:
    summary: dict[str, dict[str, float]] = {}
    for column in columns:
        series = np.asarray(frame[column], dtype=float)
        summary[column] = {
            "mean": float(np.mean(series)),
            "median": float(np.median(series)),
            "q025": float(np.quantile(series, 0.025)),
            "q975": float(np.quantile(series, 0.975)),
        }
    return summary


def merged_samples(raw_dir: Path, case: str):
    from anesthetic import read_chains
    from anesthetic.samples import merge_nested_samples

    runs = [
        read_chains(str(raw_dir / f"{case}_seed{seed}"))
        for seed in SEEDS
    ]
    return merge_nested_samples(runs)


def tension_analysis(raw_dir: Path, nsamples: int) -> dict[str, object]:
    from anesthetic.tension import tension_stats

    np.random.seed(20260712)

    samples_a = merged_samples(raw_dir, "A")
    samples_bc = merged_samples(raw_dir, "B_concordant")
    samples_abc = merged_samples(raw_dir, "AB_concordant")
    samples_bs = merged_samples(raw_dir, "B_shifted")
    samples_abs = merged_samples(raw_dir, "AB_shifted")

    stats_a = samples_a.stats(nsamples=nsamples)
    stats_bc = samples_bc.stats(nsamples=nsamples)
    stats_abc = samples_abc.stats(nsamples=nsamples)
    stats_bs = samples_bs.stats(nsamples=nsamples)
    stats_abs = samples_abs.stats(nsamples=nsamples)

    concordant = tension_stats(stats_abc, stats_a, stats_bc)
    shifted = tension_stats(stats_abs, stats_a, stats_bs)

    columns = ("logR", "I", "logS", "d_G", "p", "sigma")
    concordant_summary = summarize_distribution(concordant, columns)
    shifted_summary = summarize_distribution(shifted, columns)

    # Broad-prior Gaussian expectations for two unit-variance measurements.
    # logS = d/2 - chi2_distance/2, with d=1.
    expected_concordant_logS = 0.5
    expected_shifted_logS = 0.5 - 0.5 * ((4.0 - 0.0) ** 2 / (1.0 + 1.0))
    expected_shifted_p = float(chi2.sf(1.0 - 2.0 * expected_shifted_logS, df=1))
    expected_shifted_sigma = float(norm.isf(expected_shifted_p / 2.0))

    c_sigma = concordant_summary["sigma"]["median"]
    s_sigma = shifted_summary["sigma"]["median"]
    s_p = shifted_summary["p"]["median"]
    c_logs = concordant_summary["logS"]["median"]
    s_logs = shifted_summary["logS"]["median"]

    checks = {
        "concordant_sigma_below_1": c_sigma < 1.0,
        "shifted_sigma_above_2_2": s_sigma > 2.2,
        "shifted_p_below_0_03": s_p < 0.03,
        "shifted_exceeds_concordant_by_1_5_sigma": (s_sigma - c_sigma) > 1.5,
        "concordant_logS_within_0_5_of_expectation":
            abs(c_logs - expected_concordant_logS) <= 0.5,
        "shifted_logS_within_0_5_of_expectation":
            abs(s_logs - expected_shifted_logS) <= 0.5,
    }

    return {
        "concordant": concordant_summary,
        "shifted": shifted_summary,
        "analytic_expectations": {
            "concordant_logS": expected_concordant_logS,
            "concordant_p": 1.0,
            "concordant_sigma": 0.0,
            "shifted_logS": expected_shifted_logS,
            "shifted_p": expected_shifted_p,
            "shifted_sigma": expected_shifted_sigma,
        },
        "checks": checks,
        "pass": all(checks.values()),
    }


def write_markdown_report(summary: dict[str, object], path: Path) -> None:
    run_rows = []
    for row in summary["runs"]:
        run_rows.append(
            "| {case} | {seed} | {logZ:.6f} | {logZerr:.6f} | "
            "{analytic_logZ:.6f} | {absolute_error:.6f} | {status} |".format(
                **row,
                status="PASS" if row["analytic_pass"] else "FAIL",
            )
        )

    repeat_rows = []
    for case, values in summary["repeat_agreement"].items():
        repeat_rows.append(
            f"| {case} | {values['absolute_logZ_difference']:.6f} | "
            f"{values['tolerance']:.6f} | "
            f"{'PASS' if values['pass'] else 'FAIL'} |"
        )

    tension = summary["tension"]
    c = tension["concordant"]
    s = tension["shifted"]
    report = f"""# Synthetic execution-lock benchmark

Overall status: **{"PASS" if summary["overall_pass"] else "FAIL"}**

## Software

```text
Python: {summary["software"]["python"]}
Cobaya: {summary["software"]["cobaya"]}
anesthetic: {summary["software"]["anesthetic"]}
mpi4py: {summary["software"]["mpi4py"]}
PolyChordLite commit: {summary["software"]["polychordlite_commit"]}
```

## Evidence versus analytic result

| Case | Seed | numerical log Z | reported error | analytic log Z | absolute error | Status |
|---|---:|---:|---:|---:|---:|---|
{chr(10).join(run_rows)}

## Independent-seed agreement

| Case | absolute difference | frozen tolerance | Status |
|---|---:|---:|---|
{chr(10).join(repeat_rows)}

## Suspiciousness benchmark

| Pair | median log S | median p | median sigma |
|---|---:|---:|---:|
| Concordant | {c["logS"]["median"]:.6f} | {c["p"]["median"]:.6f} | {c["sigma"]["median"]:.6f} |
| Shifted | {s["logS"]["median"]:.6f} | {s["p"]["median"]:.6f} | {s["sigma"]["median"]:.6f} |

Analytic broad-prior expectations:

- Concordant: log S = {tension["analytic_expectations"]["concordant_logS"]:.6f},
  p = 1, sigma = 0.
- Shifted: log S = {tension["analytic_expectations"]["shifted_logS"]:.6f},
  p = {tension["analytic_expectations"]["shifted_p"]:.6f},
  sigma = {tension["analytic_expectations"]["shifted_sigma"]:.6f}.

## Acceptance checks

```json
{json.dumps(summary["checks"], indent=2, sort_keys=True)}
```
"""
    path.write_text(report, encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("results/synthetic_benchmark"),
    )
    parser.add_argument("--nlive", type=int, default=500)
    parser.add_argument("--num-repeats", type=int, default=20)
    parser.add_argument("--precision", type=float, default=1e-3)
    parser.add_argument("--anesthetic-samples", type=int, default=4000)
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    comm = MPI.COMM_WORLD
    rank = comm.Get_rank()

    output_dir = args.output_dir.resolve()
    raw_dir = output_dir / "raw"

    abort_message = None
    if rank == 0:
        if output_dir.exists() and not args.overwrite:
            abort_message = (
                f"{output_dir} already exists; use --overwrite deliberately"
            )
        elif output_dir.exists():
            shutil.rmtree(output_dir)
        if abort_message is None:
            raw_dir.mkdir(parents=True, exist_ok=True)

    abort_message = comm.bcast(abort_message, root=0)
    if abort_message is not None:
        if rank == 0:
            print(abort_message, file=sys.stderr)
        return 2
    comm.Barrier()

    results: list[RunResult] = []
    for case, means in CASES.items():
        for seed in SEEDS:
            if rank == 0:
                print(f"\n=== {case}, seed={seed} ===", flush=True)
            result = run_case(
                case=case,
                means=means,
                seed=seed,
                raw_dir=raw_dir,
                nlive=args.nlive,
                num_repeats=args.num_repeats,
                precision=args.precision,
            )
            if rank == 0 and result is not None:
                results.append(result)

    comm.Barrier()
    if rank != 0:
        return 0

    repeat_checks = repeat_agreement(results)
    tension = tension_analysis(raw_dir, args.anesthetic_samples)

    analytic_checks = {
        f"{result.case}_seed{result.seed}": result.analytic_pass
        for result in results
    }
    repeat_boolean_checks = {
        f"{case}_seed_agreement": bool(values["pass"])
        for case, values in repeat_checks.items()
    }
    tension_checks = {
        f"tension_{name}": bool(value)
        for name, value in tension["checks"].items()
    }
    all_checks = {
        **analytic_checks,
        **repeat_boolean_checks,
        **tension_checks,
    }
    overall_pass = all(all_checks.values())

    repo_root = Path.cwd()
    summary = {
        "benchmark": {
            "prior": {"distribution": "uniform", "lower": LOWER, "upper": UPPER},
            "cases": {key: list(value) for key, value in CASES.items()},
            "seeds": list(SEEDS),
            "nlive": args.nlive,
            "num_repeats": args.num_repeats,
            "precision_criterion": args.precision,
            "anesthetic_resamples": args.anesthetic_samples,
        },
        "software": {
            "python": sys.version.split()[0],
            "cobaya": package_version("cobaya"),
            "anesthetic": package_version("anesthetic"),
            "getdist": package_version("getdist"),
            "mpi4py": package_version("mpi4py"),
            "numpy": package_version("numpy"),
            "scipy": package_version("scipy"),
            "pandas": package_version("pandas"),
            "polychordlite_commit": git_commit(repo_root / "external/PolyChordLite"),
        },
        "runs": [
            {
                "case": result.case,
                "seed": result.seed,
                "root": result.root,
                "logZ": result.logZ,
                "logZerr": result.logZerr,
                "analytic_logZ": result.analytic_logZ,
                "absolute_error": result.absolute_error,
                "analytic_pass": result.analytic_pass,
            }
            for result in results
        ],
        "repeat_agreement": repeat_checks,
        "tension": tension,
        "checks": all_checks,
        "overall_pass": overall_pass,
    }

    summary_path = output_dir / "summary.json"
    report_path = output_dir / "REPORT.md"
    summary_path.write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    write_markdown_report(summary, report_path)

    print(f"\nSummary: {summary_path}")
    print(f"Report:  {report_path}")
    print(f"Overall: {'PASS' if overall_pass else 'FAIL'}")
    return 0 if overall_pass else 1


if __name__ == "__main__":
    raise SystemExit(main())
