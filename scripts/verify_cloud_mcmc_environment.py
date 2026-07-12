#!/usr/bin/env python3
"""Verify the cloud deployment before likelihood-data installation."""

from __future__ import annotations

import json
import os
import platform
import re
import subprocess
import sys
from importlib.metadata import distributions, version
from pathlib import Path


EXPECTED = {
    "cobaya": "3.5.4",
    "camb": "1.5.0",
    "getdist": "1.7.7",
    "arviz": "0.23.4",
    "mpi4py": "4.1.2",
}
EXPECTED_BRANCH = "confirmatory-analysis"
EXPECTED_MPI_SIZE = 4

ROOT = Path(
    subprocess.check_output(
        ["git", "rev-parse", "--show-toplevel"],
        text=True,
    ).strip()
)
OUTPUT = ROOT / "results/provenance/cloud_deployment_pre_likelihood"


def run(command, cwd=None):
    return subprocess.run(
        command,
        cwd=cwd or ROOT,
        text=True,
        capture_output=True,
    )


def parse_act_commit():
    path = ROOT / "results/provenance/act-lite-pin-decision.txt"
    pattern = re.compile(r"^Selected commit:\s*([0-9a-fA-F]{40})\s*$")
    for line in path.read_text().splitlines():
        match = pattern.match(line)
        if match:
            return match.group(1).lower()
    raise RuntimeError("Could not parse ACT-lite commit")


def installed_act_commit():
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
            matches.append(
                {
                    "name": dist.metadata.get("Name", dist.name),
                    "version": dist.version,
                    "direct_url": data,
                }
            )
    if len(matches) != 1:
        raise RuntimeError(
            f"Expected one ACT-lite installation; found {len(matches)}"
        )
    commit = (
        matches[0]["direct_url"]
        .get("vcs_info", {})
        .get("commit_id", "")
        .lower()
    )
    return matches[0], commit


def checksum(manifest, cwd):
    result = run(["sha256sum", "-c", str(manifest)], cwd=cwd)
    lines = [line for line in result.stdout.splitlines() if line.strip()]
    failures = [line for line in lines if not line.endswith(": OK")]
    return {
        "returncode": result.returncode,
        "entries": len(lines),
        "failures": failures,
        "stderr": result.stderr.strip(),
        "pass": result.returncode == 0 and not failures,
    }


def mem_gib():
    for line in Path("/proc/meminfo").read_text().splitlines():
        if line.startswith("MemTotal:"):
            return float(line.split()[1]) / 1024 / 1024
    return None


def main():
    if OUTPUT.exists():
        raise SystemExit(f"{OUTPUT} already exists; refusing to overwrite")
    OUTPUT.mkdir(parents=True)

    bootstrap = json.loads(
        (
            ROOT
            / "results/provenance/cloud_mcmc_environment/environment.json"
        ).read_text()
    )

    branch = run(["git", "branch", "--show-current"]).stdout.strip()
    head = run(["git", "rev-parse", "HEAD"]).stdout.strip()
    status = run(["git", "status", "--porcelain"]).stdout.strip()

    expected_act = parse_act_commit()
    act_record, actual_act = installed_act_commit()

    versions = {name: version(name) for name in EXPECTED}

    mpi = run(
        [
            "mpirun",
            "-np",
            "4",
            sys.executable,
            "-c",
            (
                "from mpi4py import MPI; "
                "print(f'rank={MPI.COMM_WORLD.rank} "
                "size={MPI.COMM_WORLD.size}')"
            ),
        ]
    )
    mpi_lines = sorted(
        line.strip()
        for line in mpi.stdout.splitlines()
        if line.strip()
    )
    mpi_pass = (
        mpi.returncode == 0
        and len(mpi_lines) == EXPECTED_MPI_SIZE
        and all("size=4" in line for line in mpi_lines)
    )

    checksum_groups = {
        "resume_seed": checksum(
            ROOT
            / "results/provenance/mcmc-extension-seed-checksums.txt",
            ROOT,
        ),
        "released_chains": checksum(
            Path("checksums.txt"),
            ROOT / "data/derived",
        ),
        "raw_data": checksum(
            ROOT / "data/raw/checksums.txt",
            ROOT,
        ),
    }

    packages_path = Path(
        os.environ.get(
            "COBAYA_PACKAGES_PATH",
            "/opt/cobaya-packages-act-dr6",
        )
    ).resolve()

    checks = {
        "branch_matches": branch == EXPECTED_BRANCH,
        "head_matches_bootstrap": head == bootstrap["repository_commit"],
        "tracked_worktree_clean": status == "",
        "python_3_11": platform.python_version().startswith("3.11."),
        "package_versions_match": all(
            versions[name] == wanted
            for name, wanted in EXPECTED.items()
        ),
        "act_lite_commit_matches": actual_act == expected_act,
        "mpi_four_rank_pass": mpi_pass,
        "resume_seed_checksums_pass": checksum_groups["resume_seed"]["pass"],
        "released_chain_checksums_pass": checksum_groups[
            "released_chains"
        ]["pass"],
        "raw_data_checksums_pass": checksum_groups["raw_data"]["pass"],
        "packages_path_exists": packages_path.is_dir(),
        "packages_path_matches_bootstrap": (
            str(packages_path)
            == str(Path(bootstrap["cobaya_packages_path"]).resolve())
        ),
        "at_least_eight_cpus": (os.cpu_count() or 0) >= 8,
        "at_least_16_GiB_memory": (mem_gib() or 0) >= 16,
        "bootstrap_no_likelihood_data": (
            bootstrap["likelihood_data_downloaded"] is False
        ),
        "bootstrap_no_likelihood_evaluation": (
            bootstrap["likelihood_evaluated"] is False
        ),
        "bootstrap_no_mcmc": bootstrap["mcmc_started"] is False,
        "no_target_statistic_computed": True,
    }

    report = {
        "purpose": "pre-likelihood cloud deployment verification",
        "repository": {
            "root": str(ROOT),
            "branch": branch,
            "head": head,
            "bootstrap_head": bootstrap["repository_commit"],
            "tracked_status": status.splitlines(),
        },
        "machine": {
            "hostname": platform.node(),
            "logical_cpus": os.cpu_count(),
            "memory_GiB": mem_gib(),
        },
        "python": {
            "executable": sys.executable,
            "version": platform.python_version(),
        },
        "packages": versions,
        "act_lite": {
            "expected_commit": expected_act,
            "installed_commit": actual_act,
            "record": act_record,
        },
        "mpi": {
            "returncode": mpi.returncode,
            "stdout": mpi_lines,
            "stderr": mpi.stderr.strip(),
            "pass": mpi_pass,
        },
        "checksums": checksum_groups,
        "packages_path": str(packages_path),
        "checks": checks,
        "overall_pass": all(checks.values()),
        "likelihood_data_installed": False,
        "likelihood_evaluated": False,
        "mcmc_started": False,
        "target_statistic_computed": False,
    }

    (OUTPUT / "verification.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n"
    )
    (OUTPUT / "REPORT.md").write_text(
        "# Cloud deployment verification\n\n"
        f"Overall status: **{'PASS' if report['overall_pass'] else 'FAIL'}**\n\n"
        "No likelihood data were installed, no likelihood was evaluated, "
        "no MCMC was started, and no target statistic was computed.\n\n"
        "```json\n"
        + json.dumps(checks, indent=2, sort_keys=True)
        + "\n```\n"
    )

    print(f"Overall: {'PASS' if report['overall_pass'] else 'FAIL'}")
    print(f"Output: {OUTPUT}")
    if not report["overall_pass"]:
        print(
            "Failed checks:",
            [name for name, passed in checks.items() if not passed],
        )
    return 0 if report["overall_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
