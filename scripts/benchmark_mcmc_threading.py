#!/usr/bin/env python3
"""Target-blind four-rank CAMB/Cobaya threading benchmark.

Each MPI rank loads a different existing chain, performs one untimed warm-up
posterior evaluation, then evaluates distinct existing chain points. Only
technical timings, names, hashes and finite/non-finite status are recorded.
No sampler is created and no chain file is modified.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import platform
import subprocess
import sys
import time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
from cobaya.model import get_model
from cobaya.yaml import yaml_load_file
from mpi4py import MPI

from locked_cobaya_runtime import (
    DATASETS,
    prepare_locked_runtime,
    sha256_file,
    verify_thread_environment,
)

EXPECTED_MPI_RANKS = 4


def repo_root() -> Path:
    return Path(
        subprocess.check_output(
            ["git", "rev-parse", "--show-toplevel"], text=True
        ).strip()
    ).resolve()


def read_header_and_tail(path: Path, count: int) -> tuple[list[str], list[list[float]], int]:
    header: list[str] | None = None
    rows: deque[list[float]] = deque(maxlen=count)
    data_rows = 0
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            stripped = line.strip()
            if not stripped:
                continue
            if stripped.startswith("#"):
                if header is None:
                    header = stripped.lstrip("#").split()
                continue
            values = [float(value) for value in stripped.split()]
            if not all(math.isfinite(value) for value in values):
                raise RuntimeError(f"Non-finite row in {path}")
            rows.append(values)
            data_rows += 1
    if header is None:
        raise RuntimeError(f"No header found in {path}")
    if len(rows) < count:
        raise RuntimeError(
            f"{path} has only {len(rows)} usable tail rows; need {count}"
        )
    if any(len(row) != len(header) for row in rows):
        raise RuntimeError(f"Column-count mismatch in {path}")
    return header, list(rows), data_rows


def finite_posterior_record(posterior: dict[str, Any], expected_likelihoods: set[str]) -> dict[str, Any]:
    loglikes = posterior.get("loglikes", {})
    return {
        "logposterior_finite": bool(np.isfinite(posterior.get("logpost", np.nan))),
        "returned_likelihood_names": sorted(loglikes),
        "likelihood_name_set_matches": set(loglikes) == expected_likelihoods,
        "all_likelihoods_finite": all(
            bool(np.isfinite(loglikes.get(name, np.nan)))
            for name in expected_likelihoods
        ),
        "numerical_values_recorded": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", choices=sorted(DATASETS), required=True)
    parser.add_argument("--omp-threads", type=int, choices=(1, 2), required=True)
    parser.add_argument("--timed-evaluations", type=int, default=3)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    comm = MPI.COMM_WORLD
    rank = comm.Get_rank()
    size = comm.Get_size()
    if size != EXPECTED_MPI_RANKS:
        raise RuntimeError(f"Expected {EXPECTED_MPI_RANKS} MPI ranks; found {size}")
    if args.timed_evaluations < 2:
        raise RuntimeError("At least two timed evaluations are required")

    root = repo_root()
    dataset = DATASETS[args.dataset]
    output = args.output.resolve()
    packages_path = Path(os.environ["COBAYA_PACKAGES_PATH"]).resolve()

    thread_gate = verify_thread_environment(args.omp_threads)
    template_path = (root / dataset["runtime_template"]).resolve()
    chain_path = (
        root / dataset["directory"] / f"{dataset['prefix']}.{rank + 1}.txt"
    ).resolve()
    if not template_path.is_file():
        raise RuntimeError(f"Missing runtime template: {template_path}")
    if not chain_path.is_file():
        raise RuntimeError(f"Missing chain for rank {rank}: {chain_path}")

    info = yaml_load_file(str(template_path))
    runtime_info, runtime_gate = prepare_locked_runtime(info, packages_path)
    runtime_info["output"] = None
    runtime_info["timing"] = False
    runtime_info.pop("sampler", None)
    for key in ("resume", "force", "test", "debug", "minimize"):
        runtime_info.pop(key, None)

    declared_likelihoods = set((runtime_info.get("likelihood") or {}).keys())
    expected_likelihoods = set(dataset["likelihoods"])
    if declared_likelihoods != expected_likelihoods:
        raise RuntimeError(
            f"Likelihood set mismatch: declared={sorted(declared_likelihoods)}, "
            f"expected={sorted(expected_likelihoods)}"
        )

    chain_sha256_before = sha256_file(chain_path)
    header, rows, total_data_rows = read_header_and_tail(
        chain_path, args.timed_evaluations + 1
    )
    row_dicts = [dict(zip(header, row, strict=True)) for row in rows]

    model = None
    initialization_start = time.perf_counter()
    model = get_model(runtime_info)
    initialization_seconds = time.perf_counter() - initialization_start

    try:
        sampled_names = list(model.parameterization.sampled_params())
        missing = sorted(set(sampled_names) - set(header))
        if missing:
            raise RuntimeError(f"Chain lacks sampled parameters: {missing}")
        points = [
            {name: row[name] for name in sampled_names}
            for row in row_dicts
        ]

        warmup = model.logposterior(points[0], as_dict=True)
        warmup_status = finite_posterior_record(warmup, expected_likelihoods)
        if not all(
            warmup_status[key]
            for key in (
                "logposterior_finite",
                "likelihood_name_set_matches",
                "all_likelihoods_finite",
            )
        ):
            raise RuntimeError(f"Warm-up evaluation failed: {warmup_status}")

        local_times: list[float] = []
        round_wall_times: list[float] = []
        evaluation_statuses: list[dict[str, Any]] = []

        for point in points[1:]:
            comm.Barrier()
            started = time.perf_counter()
            posterior = model.logposterior(point, as_dict=True)
            local_elapsed = time.perf_counter() - started
            all_elapsed = comm.gather(local_elapsed, root=0)
            status = finite_posterior_record(posterior, expected_likelihoods)
            all_status = comm.gather(status, root=0)
            local_times.append(local_elapsed)
            if rank == 0:
                assert all_elapsed is not None and all_status is not None
                round_wall_times.append(max(all_elapsed))
                evaluation_statuses.extend(all_status)
            comm.Barrier()

        initialization_all = comm.gather(initialization_seconds, root=0)
        local_times_all = comm.gather(local_times, root=0)
        chain_sha256_after = sha256_file(chain_path)
        chain_unchanged = chain_sha256_after == chain_sha256_before
        chain_metadata = comm.gather(
            {
                "rank": rank,
                "chain": str(chain_path.relative_to(root)),
                "file_size": chain_path.stat().st_size,
                "sha256_before": chain_sha256_before,
                "sha256_after": chain_sha256_after,
                "unchanged": chain_unchanged,
                "data_rows": total_data_rows,
                "tail_rows_used": args.timed_evaluations + 1,
                "parameter_values_recorded": False,
            },
            root=0,
        )

        if rank == 0:
            assert initialization_all is not None
            assert local_times_all is not None
            assert chain_metadata is not None
            flattened = [value for values in local_times_all for value in values]
            checks = {
                "mpi_size_is_four": size == EXPECTED_MPI_RANKS,
                "thread_environment_matches": all(thread_gate["checks"].values()),
                "runtime_gates_passed": True,
                "exact_likelihood_set": declared_likelihoods == expected_likelihoods,
                "all_evaluations_finite": all(
                    status["logposterior_finite"]
                    and status["likelihood_name_set_matches"]
                    and status["all_likelihoods_finite"]
                    for status in evaluation_statuses
                ),
                "no_sampler_created": True,
                "no_chain_file_modified": all(
                    item["unchanged"] for item in chain_metadata
                ),
                "no_target_statistic_computed": True,
                "no_numerical_posterior_values_recorded": True,
                "no_parameter_values_recorded": True,
            }
            total_evaluations = size * args.timed_evaluations
            timed_wall_seconds = sum(round_wall_times)
            report = {
                "purpose": "target-blind four-rank CAMB threading benchmark",
                "created_utc": datetime.now(timezone.utc).isoformat(),
                "overall_pass": all(checks.values()),
                "dataset": args.dataset,
                "mpi_ranks": size,
                "omp_threads_per_rank": args.omp_threads,
                "timed_evaluations_per_rank": args.timed_evaluations,
                "total_timed_evaluations": total_evaluations,
                "repository": {
                    "root": str(root),
                    "commit": subprocess.check_output(
                        ["git", "rev-parse", "HEAD"], cwd=root, text=True
                    ).strip(),
                    "branch": subprocess.check_output(
                        ["git", "branch", "--show-current"], cwd=root, text=True
                    ).strip(),
                },
                "machine": {
                    "hostname": platform.node(),
                    "logical_cpus": os.cpu_count(),
                    "python": sys.version,
                },
                "inputs": {
                    "runtime_template": str(template_path.relative_to(root)),
                    "runtime_template_sha256": sha256_file(template_path),
                    "chains": chain_metadata,
                },
                "runtime_gate": runtime_gate,
                "thread_gate": thread_gate,
                "timing_seconds": {
                    "initialization_by_rank": initialization_all,
                    "initialization_max": max(initialization_all),
                    "local_evaluations_by_rank": local_times_all,
                    "local_evaluation_median": float(np.median(flattened)),
                    "local_evaluation_max": max(flattened),
                    "round_wall_times": round_wall_times,
                    "timed_wall_total": timed_wall_seconds,
                    "throughput_evaluations_per_second": (
                        total_evaluations / timed_wall_seconds
                    ),
                },
                "checks": checks,
                "numerical_likelihood_values_recorded": False,
                "parameter_values_recorded": False,
                "target_statistic_computed": False,
            }
            if output.exists():
                raise RuntimeError(f"Refusing to overwrite {output}")
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(
                json.dumps(report, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            print(f"Benchmark dataset={args.dataset} threads={args.omp_threads}: PASS")
            print(f"Output: {output}")
            return 0
        return 0
    finally:
        if model is not None:
            model.close()


if __name__ == "__main__":
    raise SystemExit(main())
