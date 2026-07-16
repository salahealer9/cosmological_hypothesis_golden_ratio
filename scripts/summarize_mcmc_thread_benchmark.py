#!/usr/bin/env python3
"""Summarize and select the locked MCMC thread count by a fixed rule."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import platform
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from locked_cobaya_runtime import DATASETS, sha256_file

THREADS = (1, 2)
MIN_GEOMETRIC_SPEEDUP_FOR_TWO = 1.05
MIN_PER_DATASET_SPEEDUP_FOR_TWO = 0.95


def geometric_mean(values: list[float]) -> float:
    if not values or any(value <= 0 for value in values):
        raise RuntimeError(f"Invalid geometric-mean inputs: {values}")
    return math.exp(sum(math.log(value) for value in values) / len(values))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    args = parser.parse_args()

    root = args.root.resolve()
    if not root.is_dir():
        raise RuntimeError(f"Benchmark root does not exist: {root}")

    runs: dict[str, dict[int, dict[str, Any]]] = {}
    for dataset in DATASETS:
        runs[dataset] = {}
        for threads in THREADS:
            path = root / dataset / f"threads_{threads}" / "verification.json"
            if not path.is_file():
                raise RuntimeError(f"Missing benchmark result: {path}")
            record = json.loads(path.read_text(encoding="utf-8"))
            if record.get("overall_pass") is not True:
                raise RuntimeError(f"Benchmark did not pass: {path}")
            if record.get("dataset") != dataset:
                raise RuntimeError(f"Dataset mismatch in {path}")
            if record.get("omp_threads_per_rank") != threads:
                raise RuntimeError(f"Thread-count mismatch in {path}")
            runs[dataset][threads] = record

    per_dataset: dict[str, dict[str, float]] = {}
    speedups: list[float] = []
    for dataset in DATASETS:
        one = runs[dataset][1]["timing_seconds"][
            "throughput_evaluations_per_second"
        ]
        two = runs[dataset][2]["timing_seconds"][
            "throughput_evaluations_per_second"
        ]
        speedup = two / one
        speedups.append(speedup)
        per_dataset[dataset] = {
            "threads_1_throughput": one,
            "threads_2_throughput": two,
            "threads_2_over_threads_1_speedup": speedup,
        }

    geometric_speedup = geometric_mean(speedups)
    minimum_speedup = min(speedups)
    select_two = (
        geometric_speedup >= MIN_GEOMETRIC_SPEEDUP_FOR_TWO
        and minimum_speedup >= MIN_PER_DATASET_SPEEDUP_FOR_TWO
    )
    selected_threads = 2 if select_two else 1
    reason = (
        "two threads met both the aggregate and per-dataset speed rules"
        if select_two
        else "one thread retained because two threads did not clear both predeclared thresholds"
    )

    checks = {
        "all_six_runs_present": sum(len(value) for value in runs.values()) == 6,
        "all_six_runs_passed": all(
            runs[dataset][threads]["overall_pass"]
            for dataset in DATASETS
            for threads in THREADS
        ),
        "selected_threads_is_one_or_two": selected_threads in THREADS,
        "no_target_statistic_computed": True,
    }
    report = {
        "purpose": "target-blind MCMC thread-configuration selection",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "overall_pass": all(checks.values()),
        "selection_rule": {
            "candidate_threads_per_rank": list(THREADS),
            "mpi_ranks": 4,
            "choose_two_only_if_geometric_speedup_at_least": (
                MIN_GEOMETRIC_SPEEDUP_FOR_TWO
            ),
            "and_each_dataset_speedup_at_least": (
                MIN_PER_DATASET_SPEEDUP_FOR_TWO
            ),
            "otherwise_choose": 1,
        },
        "per_dataset": per_dataset,
        "aggregate": {
            "geometric_speedup_threads_2_over_1": geometric_speedup,
            "minimum_dataset_speedup_threads_2_over_1": minimum_speedup,
        },
        "selected_threads_per_rank": selected_threads,
        "selection_reason": reason,
        "checks": checks,
        "target_statistic_computed": False,
    }

    verification = root / "verification.json"
    if verification.exists():
        raise RuntimeError(f"Refusing to overwrite {verification}")
    verification.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    lines = [
        "# Four-rank MCMC threading benchmark",
        "",
        f"Overall status: **{'PASS' if report['overall_pass'] else 'FAIL'}**",
        "",
        "The benchmark performed finite, target-blind posterior evaluations at existing chain points. No sampler or MCMC chain was started.",
        "",
        "## Fixed selection rule",
        "",
        (
            "Choose two OpenMP threads per rank only when the geometric-mean "
            f"throughput speedup is at least {MIN_GEOMETRIC_SPEEDUP_FOR_TWO:.2f} "
            "and no individual dataset is slower than "
            f"{MIN_PER_DATASET_SPEEDUP_FOR_TWO:.2f} times the one-thread result."
        ),
        "",
        "## Results",
        "",
    ]
    for dataset, values in per_dataset.items():
        lines.append(
            f"- `{dataset}`: two/one throughput ratio "
            f"`{values['threads_2_over_threads_1_speedup']:.6f}`"
        )
    lines.extend(
        [
            "",
            f"Geometric-mean speedup: `{geometric_speedup:.6f}`",
            "",
            f"Selected OpenMP threads per MPI rank: **{selected_threads}**",
            "",
            f"Reason: {reason}.",
            "",
            "No target statistic, hypothesis residual, posterior summary, or scientific verdict was computed.",
        ]
    )
    (root / "REPORT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"Overall: {'PASS' if report['overall_pass'] else 'FAIL'}")
    print(f"Selected threads per rank: {selected_threads}")
    print(f"Output: {root}")
    return 0 if report["overall_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
