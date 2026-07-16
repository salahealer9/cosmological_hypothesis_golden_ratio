#!/usr/bin/env python3
"""Controlled append-only four-rank Cobaya MCMC extension launcher.

The launcher refuses to run without the frozen execution lock, verifies the
original released-chain prefix of every staged chain, applies only the locked
runtime compatibility corrections, and runs a finite accepted-row segment.
It never computes the project target statistic.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import socket
import subprocess
import sys
import time
import tomllib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml
from cobaya.run import run
from cobaya.yaml import yaml_load_file
from mpi4py import MPI

from locked_cobaya_runtime import (
    DATASETS,
    prepare_locked_runtime,
    sha256_file,
    verify_thread_environment,
)

EXPECTED_MPI_RANKS = 4
SEGMENT_LABEL_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
CRITICAL_PATHS = {
    "config/confirmatory_execution_lock.toml",
    "config/chain_ingestion_lock.toml",
    "config/mcmc_extension_execution_lock.toml",
    "config/mcmc_extension_runtime_inputs/planck_lcdm_camb.yaml",
    "config/mcmc_extension_runtime_inputs/actlite_lcdm_camb.yaml",
    "config/mcmc_extension_runtime_inputs/p-actlite_lcdm_camb.yaml",
    "scripts/locked_cobaya_runtime.py",
    "scripts/run_mcmc_extension.py",
    "scripts/run_locked_mcmc_segment.sh",
}


def repository_root() -> Path:
    return Path(
        subprocess.check_output(
            ["git", "rev-parse", "--show-toplevel"], text=True
        ).strip()
    ).resolve()


def git(root: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=root,
        text=True,
        capture_output=True,
        check=check,
    )


def count_data_rows(path: Path) -> int:
    count = 0
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            stripped = line.strip()
            if stripped and not stripped.startswith("#"):
                count += 1
    return count


def file_is_prefix(prefix: Path, candidate: Path) -> bool:
    if candidate.stat().st_size < prefix.stat().st_size:
        return False
    with prefix.open("rb") as left, candidate.open("rb") as right:
        while True:
            block = left.read(1024 * 1024)
            if not block:
                return True
            if right.read(len(block)) != block:
                return False


def load_seed_map(root: Path) -> dict[str, Any]:
    path = root / "results/provenance/mcmc_extension_seed_map.json"
    return json.loads(path.read_text(encoding="utf-8"))


def find_seed_mapping(record: dict[str, Any], destination: str) -> dict[str, Any]:
    matches = [
        item for item in record["copied_files"]
        if item["destination"] == destination
    ]
    if len(matches) != 1:
        raise RuntimeError(
            f"Expected one seed mapping for {destination}; found {len(matches)}"
        )
    return matches[0]


def inspect_chain_state(root: Path, dataset_name: str) -> dict[str, Any]:
    dataset = DATASETS[dataset_name]
    directory = (root / dataset["directory"]).resolve()
    prefix = dataset["prefix"]
    seed_map = load_seed_map(root)
    record = seed_map[dataset_name]

    numbered = sorted(directory.glob(f"{prefix}.[1-4].txt"))
    if [path.name for path in numbered] != [
        f"{prefix}.{number}.txt" for number in range(1, 5)
    ]:
        raise RuntimeError(f"Expected exactly four numbered chains in {directory}")

    chains: list[dict[str, Any]] = []
    for number, current in enumerate(numbered, 1):
        destination = current.relative_to(root).as_posix()
        mapping = find_seed_mapping(record, destination)
        source = (root / mapping["source"]).resolve()
        if not source.is_file():
            raise RuntimeError(f"Missing original released chain: {source}")
        source_hash = sha256_file(source)
        if source_hash != mapping["source_sha256"]:
            raise RuntimeError(f"Original source hash mismatch: {source}")
        if not file_is_prefix(source, current):
            raise RuntimeError(f"Staged chain is not append-only from source: {current}")
        source_rows = count_data_rows(source)
        current_rows = count_data_rows(current)
        chains.append(
            {
                "number": number,
                "source": source.relative_to(root).as_posix(),
                "current": current.relative_to(root).as_posix(),
                "source_sha256": source_hash,
                "current_sha256": sha256_file(current),
                "source_rows": source_rows,
                "current_rows": current_rows,
                "appended_rows_total": current_rows - source_rows,
                "append_only": True,
            }
        )

    checkpoint_path = directory / f"{prefix}.checkpoint"
    checkpoint = yaml.safe_load(checkpoint_path.read_text(encoding="utf-8"))
    state = checkpoint["sampler"]["mcmc"]
    if state.get("mpi_size") != EXPECTED_MPI_RANKS:
        raise RuntimeError(f"Checkpoint MPI size is not four: {checkpoint_path}")
    if state.get("converged") is not False:
        raise RuntimeError(
            f"Checkpoint is marked converged; controlled extension refused: {checkpoint_path}"
        )

    return {
        "dataset": dataset_name,
        "directory": str(directory.relative_to(root)),
        "prefix": prefix,
        "chains": chains,
        "checkpoint": {
            "path": checkpoint_path.relative_to(root).as_posix(),
            "sha256": sha256_file(checkpoint_path),
            "converged": state.get("converged"),
            "Rminus1_last": state.get("Rminus1_last"),
            "burn_in": state.get("burn_in"),
            "mpi_size": state.get("mpi_size"),
        },
    }


def verify_lock_and_repository(root: Path, lock_path: Path) -> dict[str, Any]:
    lock = tomllib.loads(lock_path.read_text(encoding="utf-8"))
    lock_info = lock.get("lock") or {}
    execution = lock.get("execution") or {}
    hashes = lock.get("script_hashes") or {}

    if lock_info.get("status") != "frozen_before_mcmc_extension":
        raise RuntimeError("MCMC extension lock is not frozen")
    if execution.get("mpi_ranks") != EXPECTED_MPI_RANKS:
        raise RuntimeError("Lock does not require exactly four MPI ranks")
    selected_threads = execution.get("selected_threads_per_rank")
    if selected_threads not in (1, 2):
        raise RuntimeError("Lock has no valid selected thread count")

    tag = str(lock_info.get("tag", ""))
    if not tag:
        raise RuntimeError("Lock does not name its signed tag")
    tag_commit_result = git(root, "rev-parse", f"{tag}^{{commit}}", check=False)
    if tag_commit_result.returncode != 0:
        raise RuntimeError(f"Required lock tag is missing: {tag}")
    tag_commit = tag_commit_result.stdout.strip()
    base_benchmark_commit = str(lock_info.get("base_benchmark_commit", ""))
    if not base_benchmark_commit:
        raise RuntimeError("Lock does not record the benchmark provenance commit")
    benchmark_ancestor = git(
        root,
        "merge-base",
        "--is-ancestor",
        base_benchmark_commit,
        tag_commit,
        check=False,
    )
    if benchmark_ancestor.returncode != 0:
        raise RuntimeError(
            "The lock tag does not descend from the recorded benchmark commit"
        )
    head = git(root, "rev-parse", "HEAD").stdout.strip()
    ancestor = git(root, "merge-base", "--is-ancestor", tag_commit, head, check=False)
    if ancestor.returncode != 0:
        raise RuntimeError("Current HEAD is not a descendant of the lock tag")

    tracked_status = git(
        root, "status", "--porcelain", "--untracked-files=no"
    ).stdout.strip()
    if tracked_status:
        raise RuntimeError(f"Tracked working tree is not clean:\n{tracked_status}")

    changed = [
        line for line in git(root, "diff", "--name-only", f"{tag_commit}..{head}")
        .stdout.splitlines()
        if line
    ]
    critical_changes = sorted(set(changed).intersection(CRITICAL_PATHS))
    if critical_changes:
        raise RuntimeError(
            f"Execution-critical files changed since the lock tag: {critical_changes}"
        )

    for relative, expected_hash in hashes.items():
        path = (root / relative).resolve()
        if not path.is_file() or sha256_file(path) != expected_hash:
            raise RuntimeError(f"Locked script hash mismatch: {relative}")

    benchmark_path = (root / lock_info["benchmark_verification"]).resolve()
    if sha256_file(benchmark_path) != lock_info["benchmark_verification_sha256"]:
        raise RuntimeError("Benchmark verification hash differs from the lock")

    return {
        "lock": lock,
        "tag": tag,
        "tag_commit": tag_commit,
        "head": head,
        "selected_threads_per_rank": selected_threads,
        "changed_since_lock": changed,
        "critical_changes_since_lock": critical_changes,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", choices=sorted(DATASETS), required=True)
    parser.add_argument("--segment-label", required=True)
    parser.add_argument("--minimum-appended-rows", type=int, required=True)
    parser.add_argument(
        "--lock",
        type=Path,
        default=Path("config/mcmc_extension_execution_lock.toml"),
    )
    parser.add_argument("--preflight-only", action="store_true")
    args = parser.parse_args()

    comm = MPI.COMM_WORLD
    rank = comm.Get_rank()
    size = comm.Get_size()
    root = repository_root()

    error: str | None = None
    root_payload: dict[str, Any] | None = None
    controller_lock: Path | None = None

    if rank == 0:
        try:
            if size != EXPECTED_MPI_RANKS:
                raise RuntimeError(f"Expected four MPI ranks; found {size}")
            if not SEGMENT_LABEL_PATTERN.fullmatch(args.segment_label):
                raise RuntimeError(f"Invalid segment label: {args.segment_label!r}")

            lock_path = (root / args.lock).resolve()
            lock_gate = verify_lock_and_repository(root, lock_path)
            selected_threads = lock_gate["selected_threads_per_rank"]
            execution = lock_gate["lock"]["execution"]
            minimum_allowed = int(execution["minimum_rows_per_segment"])
            maximum_allowed = int(execution["maximum_rows_per_segment"])
            if not minimum_allowed <= args.minimum_appended_rows <= maximum_allowed:
                raise RuntimeError(
                    f"Requested rows {args.minimum_appended_rows} outside locked "
                    f"range [{minimum_allowed}, {maximum_allowed}]"
                )

            before = inspect_chain_state(root, args.dataset)
            maximum_current_rows = max(
                item["current_rows"] for item in before["chains"]
            )
            target_rows = maximum_current_rows + args.minimum_appended_rows

            provenance_dir = (
                root
                / "results/provenance/mcmc_extensions"
                / args.dataset
                / args.segment_label
            ).resolve()
            if provenance_dir.exists():
                raise RuntimeError(f"Provenance directory exists: {provenance_dir}")

            dataset_dir = (root / DATASETS[args.dataset]["directory"]).resolve()
            controller_lock = dataset_dir / ".mcmc-extension-controller.lock"
            try:
                descriptor = os.open(
                    controller_lock,
                    os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                    0o600,
                )
            except FileExistsError as exc:
                raise RuntimeError(
                    f"Controller lock already exists: {controller_lock}"
                ) from exc
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(
                    {
                        "hostname": socket.gethostname(),
                        "pid": os.getpid(),
                        "dataset": args.dataset,
                        "segment_label": args.segment_label,
                        "created_utc": datetime.now(timezone.utc).isoformat(),
                    },
                    handle,
                    indent=2,
                )
                handle.write("\n")

            if not args.preflight_only:
                provenance_dir.mkdir(parents=True)

            root_payload = {
                "lock_gate": lock_gate,
                "before": before,
                "target_rows": target_rows,
                "provenance_dir": str(provenance_dir),
                "selected_threads": selected_threads,
            }
        except Exception as exc:  # noqa: BLE001 - broadcast exact preflight failure
            error = f"{type(exc).__name__}: {exc}"

    error = comm.bcast(error, root=0)
    if error:
        if rank == 0 and controller_lock and controller_lock.exists():
            controller_lock.unlink()
        raise RuntimeError(error)
    root_payload = comm.bcast(root_payload, root=0)
    assert root_payload is not None

    selected_threads = int(root_payload["selected_threads"])
    verify_thread_environment(selected_threads)

    if args.preflight_only:
        if rank == 0:
            print("MCMC extension preflight: PASS")
            print(f"Dataset: {args.dataset}")
            print(f"Target stored rows per chain: {root_payload['target_rows']}")
        comm.Barrier()
        if rank == 0 and controller_lock and controller_lock.exists():
            controller_lock.unlink()
        return 0

    packages_path = Path(os.environ["COBAYA_PACKAGES_PATH"]).resolve()
    dataset = DATASETS[args.dataset]
    template_path = (root / dataset["runtime_template"]).resolve()
    runtime_info: dict[str, Any] | None = None
    runtime_gate: dict[str, Any] | None = None
    runtime_error: str | None = None
    try:
        info = yaml_load_file(str(template_path))
        runtime_info, runtime_gate = prepare_locked_runtime(info, packages_path)
        output_prefix = (root / dataset["directory"] / dataset["prefix"]).resolve()
        runtime_info["output"] = str(output_prefix)
        runtime_info["resume"] = True
        runtime_info["force"] = False
        sampler = runtime_info.setdefault("sampler", {}).setdefault("mcmc", {})
        sampler["max_samples"] = int(root_payload["target_rows"])
        sampler["Rminus1_stop"] = 0.0
        sampler["Rminus1_cl_stop"] = 0.0
        sampler["output_every"] = "60s"
    except Exception as exc:  # noqa: BLE001
        runtime_error = f"{type(exc).__name__}: {exc}"

    runtime_errors = comm.gather(runtime_error, root=0)
    combined_runtime_error: str | None = None
    if rank == 0:
        failures = [item for item in (runtime_errors or []) if item]
        if failures:
            combined_runtime_error = f"Runtime preparation failed: {failures}"
            if controller_lock and controller_lock.exists():
                controller_lock.unlink()
    combined_runtime_error = comm.bcast(combined_runtime_error, root=0)
    if combined_runtime_error:
        raise RuntimeError(combined_runtime_error)
    assert runtime_info is not None and runtime_gate is not None

    started_utc = datetime.now(timezone.utc).isoformat()
    wall_start = time.perf_counter()
    run_error: str | None = None
    try:
        run(
            runtime_info,
            packages_path=str(packages_path),
            resume=True,
            force=False,
            allow_changes=True,
        )
    except Exception as exc:  # noqa: BLE001
        run_error = f"{type(exc).__name__}: {exc}"
    comm.Barrier()
    run_errors = comm.gather(run_error, root=0)

    post_error: str | None = None
    if rank == 0:
        provenance_dir = Path(root_payload["provenance_dir"])
        ended_utc = datetime.now(timezone.utc).isoformat()
        elapsed = time.perf_counter() - wall_start
        try:
            nonempty_errors = [item for item in (run_errors or []) if item]
            if nonempty_errors:
                raise RuntimeError(f"MPI ranks reported errors: {nonempty_errors}")
            after = inspect_chain_state(root, args.dataset)
            before_by_number = {
                item["number"]: item for item in root_payload["before"]["chains"]
            }
            growth = []
            for item in after["chains"]:
                old = before_by_number[item["number"]]
                growth.append(
                    {
                        "number": item["number"],
                        "rows_before": old["current_rows"],
                        "rows_after": item["current_rows"],
                        "rows_appended_this_segment": (
                            item["current_rows"] - old["current_rows"]
                        ),
                        "sha256_before": old["current_sha256"],
                        "sha256_after": item["current_sha256"],
                        "pre_segment_file_is_prefix": file_is_prefix(
                            root / old["current"], root / item["current"]
                        ),
                    }
                )
            checks = {
                "four_mpi_ranks": size == EXPECTED_MPI_RANKS,
                "all_ranks_completed_without_error": True,
                "all_chains_reached_target_rows": all(
                    item["current_rows"] >= root_payload["target_rows"]
                    for item in after["chains"]
                ),
                "all_chains_grew_by_requested_minimum": all(
                    item["rows_appended_this_segment"]
                    >= args.minimum_appended_rows
                    for item in growth
                ),
                "all_pre_segment_files_are_prefixes": all(
                    item["pre_segment_file_is_prefix"] for item in growth
                ),
                "all_chains_remain_extensions_of_original_release": all(
                    item["append_only"] for item in after["chains"]
                ),
                "checkpoint_mpi_size_four": (
                    after["checkpoint"]["mpi_size"] == EXPECTED_MPI_RANKS
                ),
                "checkpoint_not_converged": (
                    after["checkpoint"]["converged"] is False
                ),
                "no_target_statistic_computed": True,
            }
            report = {
                "purpose": "finite append-only MCMC extension segment",
                "overall_pass": all(checks.values()),
                "started_utc": started_utc,
                "ended_utc": ended_utc,
                "elapsed_seconds": elapsed,
                "dataset": args.dataset,
                "segment_label": args.segment_label,
                "minimum_appended_rows_requested": args.minimum_appended_rows,
                "target_rows": root_payload["target_rows"],
                "lock_gate": root_payload["lock_gate"],
                "runtime_gate": runtime_gate,
                "before": root_payload["before"],
                "after": after,
                "growth": growth,
                "checks": checks,
                "target_statistic_computed": False,
                "posterior_summary_computed": False,
                "scientific_verdict_computed": False,
            }
            (provenance_dir / "verification.json").write_text(
                json.dumps(report, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            lines = [
                "# Controlled MCMC extension segment",
                "",
                f"Overall status: **{'PASS' if report['overall_pass'] else 'FAIL'}**",
                "",
                f"Dataset: `{args.dataset}`",
                "",
                f"Segment: `{args.segment_label}`",
                "",
                f"Minimum requested appended rows per chain: `{args.minimum_appended_rows}`",
                "",
                f"Locked MPI layout: `4 x {selected_threads}` OpenMP thread(s)",
                "",
                "All four staged chains remained byte-for-byte append-only extensions of the original released chains.",
                "",
                "No target statistic, posterior target summary, or scientific verdict was computed.",
            ]
            (provenance_dir / "REPORT.md").write_text(
                "\n".join(lines) + "\n", encoding="utf-8"
            )
            if not report["overall_pass"]:
                raise RuntimeError(f"Post-segment integrity gate failed: {checks}")
            print("MCMC extension segment: PASS")
            print(f"Provenance: {provenance_dir}")
        except Exception as exc:  # noqa: BLE001
            post_error = f"{type(exc).__name__}: {exc}"
        finally:
            if controller_lock and controller_lock.exists():
                controller_lock.unlink()

    post_error = comm.bcast(post_error, root=0)
    if post_error:
        raise RuntimeError(post_error)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
