#!/usr/bin/env python3
"""Create the frozen MCMC-extension execution lock from benchmark provenance."""

from __future__ import annotations

import argparse
import json
import subprocess
from datetime import date
from pathlib import Path

from locked_cobaya_runtime import (
    DATASETS,
    EXPECTED_ACT_DATA_VERSION,
    EXPECTED_ACT_INPUT_FILE,
    EXPECTED_ACT_LITE_COMMIT,
    EXPECTED_CAMB_COMMIT,
    sha256_file,
)

EXPECTED_BRANCH = "confirmatory-analysis"
EXPECTED_TAG = "v0.1.3-mcmc-extension-lock"
LOCKED_SCRIPTS = (
    "scripts/locked_cobaya_runtime.py",
    "scripts/benchmark_mcmc_threading.py",
    "scripts/summarize_mcmc_thread_benchmark.py",
    "scripts/run_mcmc_thread_benchmark.sh",
    "scripts/finalize_mcmc_extension_lock.py",
    "scripts/run_mcmc_extension.py",
    "scripts/run_locked_mcmc_segment.sh",
)
RUNTIME_TEMPLATES = tuple(
    DATASETS[name]["runtime_template"] for name in DATASETS
)


def git(root: Path, *args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=root, text=True).strip()


def quote(value: str) -> str:
    return json.dumps(value)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--benchmark",
        type=Path,
        default=Path("results/provenance/mcmc_thread_benchmark/verification.json"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("config/mcmc_extension_execution_lock.toml"),
    )
    args = parser.parse_args()

    root = Path(git(Path.cwd(), "rev-parse", "--show-toplevel")).resolve()
    branch = git(root, "branch", "--show-current")
    if branch != EXPECTED_BRANCH:
        raise RuntimeError(f"Expected branch {EXPECTED_BRANCH}; found {branch}")
    status = git(root, "status", "--porcelain", "--untracked-files=no")
    if status:
        raise RuntimeError(f"Tracked working tree is not clean:\n{status}")

    benchmark = (root / args.benchmark).resolve()
    output = (root / args.output).resolve()
    if output.exists():
        raise RuntimeError(f"Refusing to overwrite {output}")
    record = json.loads(benchmark.read_text(encoding="utf-8"))
    if record.get("overall_pass") is not True:
        raise RuntimeError("Benchmark verification is not PASS")
    selected = record.get("selected_threads_per_rank")
    if selected not in (1, 2):
        raise RuntimeError("Benchmark did not select one or two threads")

    tracked_inputs = list(LOCKED_SCRIPTS + RUNTIME_TEMPLATES)
    tracked_inputs.append(benchmark.relative_to(root).as_posix())
    for relative in tracked_inputs:
        path = root / relative
        if not path.is_file():
            raise RuntimeError(f"Missing lock input: {relative}")
        tracked = subprocess.run(
            ["git", "ls-files", "--error-unmatch", relative],
            cwd=root,
            text=True,
            capture_output=True,
        )
        if tracked.returncode != 0:
            raise RuntimeError(
                f"Lock input must be committed before finalization: {relative}"
            )

    base_commit = git(root, "rev-parse", "HEAD")
    script_hashes = {
        relative: sha256_file(root / relative)
        for relative in LOCKED_SCRIPTS + RUNTIME_TEMPLATES
    }

    lines = [
        "# Frozen only after the target-blind four-rank threading benchmark.",
        "# Commit this file and create the signed tag named below before running MCMC.",
        "",
        "[lock]",
        'name = "mcmc_extension_execution_lock"',
        'version = "0.1.0"',
        'status = "frozen_before_mcmc_extension"',
        f"date = {quote(date.today().isoformat())}",
        f"tag = {quote(EXPECTED_TAG)}",
        f"base_benchmark_commit = {quote(base_commit)}",
        f"benchmark_verification = {quote(benchmark.relative_to(root).as_posix())}",
        f"benchmark_verification_sha256 = {quote(sha256_file(benchmark))}",
        'base_preregistration_tag = "v0.1.0-preregistration-freeze"',
        'base_execution_lock_tag = "v0.1.1-confirmatory-execution-lock"',
        'base_chain_ingestion_tag = "v0.1.2-chain-ingestion-lock"',
        "",
        "[execution]",
        "mpi_ranks = 4",
        f"selected_threads_per_rank = {selected}",
        "openblas_threads = 1",
        "mkl_threads = 1",
        "numexpr_threads = 1",
        'omp_proc_bind = "close"',
        'omp_places = "threads"',
        "minimum_rows_per_segment = 100",
        "maximum_rows_per_segment = 100000",
        'target_rows_rule = "max_current_stored_rows_plus_requested_minimum_growth"',
        "resume = true",
        "force = false",
        "allow_changes = true",
        'allow_changes_scope = "enumerated runtime compatibility fields and finite-segment sampler controls only"',
        "Rminus1_stop = 0.0",
        "Rminus1_cl_stop = 0.0",
        'output_every = "60s"',
        "append_only_required = true",
        "expected_numbered_chains = 4",
        "",
        "[runtime_compatibility]",
        'cobaya = "3.5.4"',
        'camb = "1.5.0"',
        'cosmorec = "2.0.3b"',
        f"camb_commit = {quote(EXPECTED_CAMB_COMMIT)}",
        f"act_lite_commit = {quote(EXPECTED_ACT_LITE_COMMIT)}",
        f"act_data_version = {quote(EXPECTED_ACT_DATA_VERSION)}",
        f"act_input_file = {quote(EXPECTED_ACT_INPUT_FILE)}",
        'derived_capability_shim = "CAMBdata.taurend advertisement only"',
        "source_yaml_modified = false",
        "installed_cobaya_source_modified = false",
        "",
        "[selection_rule]",
        "candidate_threads_per_rank = [1, 2]",
        "minimum_geometric_speedup_for_two = 1.05",
        "minimum_each_dataset_speedup_for_two = 0.95",
        'otherwise_select = "one thread per rank"',
        "",
        "[script_hashes]",
    ]
    for relative, digest in sorted(script_hashes.items()):
        lines.append(f"{quote(relative)} = {quote(digest)}")

    for dataset, config in DATASETS.items():
        lines.extend(
            [
                "",
                f"[datasets.{dataset}]",
                f"directory = {quote(config['directory'])}",
                f"prefix = {quote(config['prefix'])}",
                f"runtime_template = {quote(config['runtime_template'])}",
                "likelihoods = [",
            ]
        )
        for likelihood in config["likelihoods"]:
            lines.append(f"  {quote(likelihood)},")
        lines.append("]")

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Created: {output.relative_to(root)}")
    print(f"Selected threads per rank: {selected}")
    print(f"Required signed tag after commit: {EXPECTED_TAG}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
