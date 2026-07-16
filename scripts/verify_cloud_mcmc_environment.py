#!/usr/bin/env python3
"""Verify the cloud deployment before likelihood-data installation.

This version treats CAMB's compile-time CosmoRec capability as part of the
locked scientific environment. A stock CAMB 1.5.0 wheel must fail even when
its package version is correct.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import subprocess
import sys
from importlib.metadata import distribution, distributions, version
from pathlib import Path
from urllib.parse import unquote, urlparse


EXPECTED = {
    "cobaya": "3.5.4",
    "camb": "1.5.0",
    "getdist": "1.7.7",
    "arviz": "0.23.4",
    "mpi4py": "4.1.2",
}
EXPECTED_BRANCH = "confirmatory-analysis"
EXPECTED_MPI_SIZE = 4
EXPECTED_CAMB_COMMIT = "28e4036519155531f4ed9a4e1d8afb1579d2de11"
EXPECTED_FORUTILS_COMMIT = "fcaff9d176c0ec6a9c63b036465fbb6be6722338"
EXPECTED_COSMOREC_VERSION = "2.0.3b"
EXPECTED_COSMOREC_ARCHIVE_SHA256 = (
    "2afb82b5512f7158a0291d3a73c6520455f0e55957f2965dccc5eef82af8da1b"
)
DEFAULT_SOFTWARE_ROOT = Path("/opt/cosmology-software")

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


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def parse_act_commit():
    path = ROOT / "results/provenance/act-lite-pin-decision.txt"
    pattern = re.compile(r"^Selected commit:\s*([0-9a-fA-F]{40})\s*$")
    for line in path.read_text(encoding="utf-8").splitlines():
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


def installed_camb_record(expected_source: Path) -> dict:
    import camb

    params = camb.CAMBparams()
    params.set_classes(recombination_model="CosmoRec")

    module_path = Path(camb.__file__).resolve()
    raw = distribution("camb").read_text("direct_url.json")
    direct_url = json.loads(raw) if raw else None

    source_path = None
    editable = False
    if direct_url:
        parsed = urlparse(str(direct_url.get("url", "")))
        if parsed.scheme == "file":
            source_path = Path(unquote(parsed.path)).resolve()
        editable = bool(direct_url.get("dir_info", {}).get("editable"))

    return {
        "metadata_version": version("camb"),
        "module_version": camb.__version__,
        "module_path": str(module_path),
        "expected_source": str(expected_source),
        "module_inside_expected_source": module_path.is_relative_to(
            expected_source
        ),
        "direct_url": direct_url,
        "direct_url_source": str(source_path) if source_path else None,
        "direct_url_source_matches": source_path == expected_source,
        "editable_installation": editable,
        "recombination_class": type(params.Recomb).__name__,
        "cosmorec_class_available": type(params.Recomb).__name__ == "CosmoRec",
    }


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
    for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
        if line.startswith("MemTotal:"):
            return float(line.split()[1]) / 1024 / 1024
    return None


def main():
    if OUTPUT.exists():
        raise SystemExit(f"{OUTPUT} already exists; refusing to overwrite")
    OUTPUT.mkdir(parents=True)

    bootstrap_path = (
        ROOT / "results/provenance/cloud_mcmc_environment/environment.json"
    )
    bootstrap = json.loads(bootstrap_path.read_text(encoding="utf-8"))
    bootstrap_build = bootstrap.get("camb_cosmorec_build", {})

    software_root = Path(
        os.environ.get(
            "COSMOLOGY_SOFTWARE_ROOT",
            bootstrap.get("software_root", str(DEFAULT_SOFTWARE_ROOT)),
        )
    ).resolve()
    camb_source = Path(
        bootstrap_build.get(
            "camb_source_dir",
            software_root / "CAMB-1.5.0-cosmorec",
        )
    ).resolve()
    cosmorec_source = Path(
        bootstrap_build.get(
            "cosmorec_source_dir",
            software_root / "CosmoRec.v2.0.3b",
        )
    ).resolve()
    cosmorec_archive = Path(
        bootstrap_build.get(
            "cosmorec_archive",
            software_root / "CosmoRec.v2.0.3b.tar.gz",
        )
    ).resolve()

    branch = run(["git", "branch", "--show-current"]).stdout.strip()
    head = run(["git", "rev-parse", "HEAD"]).stdout.strip()
    status = run(["git", "status", "--porcelain"]).stdout.strip()
    bootstrap_head = bootstrap["repository_commit"]

    bootstrap_is_ancestor = (
        run(
            [
                "git",
                "merge-base",
                "--is-ancestor",
                bootstrap_head,
                head,
            ]
        ).returncode
        == 0
    )

    changed_since_bootstrap = [
        line
        for line in run(
            ["git", "diff", "--name-only", f"{bootstrap_head}..{head}"]
        ).stdout.splitlines()
        if line
    ]
    environment_critical_paths = {
        ".gitmodules",
        "config/confirmatory_execution_lock.toml",
        "config/chain_ingestion_lock.toml",
        "external/PolyChordLite",
        "results/provenance/act-lite-pin-decision.txt",
        "scripts/setup_cloud_mcmc_environment.sh",
    }
    critical_changes_since_bootstrap = sorted(
        changed_path
        for changed_path in changed_since_bootstrap
        if changed_path in environment_critical_paths
    )

    expected_act = parse_act_commit()
    act_record, actual_act = installed_act_commit()
    versions = {name: version(name) for name in EXPECTED}

    camb_record = installed_camb_record(camb_source)
    camb_commit = (
        run(["git", "rev-parse", "HEAD"], cwd=camb_source).stdout.strip()
        if (camb_source / ".git").exists()
        else ""
    )
    forutils_commit = (
        run(["git", "rev-parse", "HEAD"], cwd=camb_source / "forutils")
        .stdout.strip()
        if (camb_source / "forutils/.git").exists()
        or (camb_source / ".git/modules/forutils").exists()
        else ""
    )
    camb_tag = run(
        ["git", "describe", "--tags", "--exact-match"],
        cwd=camb_source,
    ).stdout.strip()

    cosmorec_makefile = cosmorec_source / "Makefile.in"
    camb_makefile = camb_source / "fortran/Makefile_main"
    cosmorec_fpic_assignment = (
        "CXXFLAGS = -Wall -pedantic -O2 -fPIC"
        in cosmorec_makefile.read_text(encoding="utf-8").splitlines()
        if cosmorec_makefile.is_file()
        else False
    )
    camb_makefile_text = (
        camb_makefile.read_text(encoding="utf-8")
        if camb_makefile.is_file()
        else ""
    )
    camb_makefile_cosmorec = (
        "RECOMBINATION_FILES = recfast cosmorec" in camb_makefile_text
        and f"COSMOREC_PATH = {cosmorec_source}" in camb_makefile_text
    )

    camblib = camb_source / "camb/camblib.so"
    cosmorec_lib = cosmorec_source / "libCosmoRec.a"
    ldd = run(["ldd", str(camblib)]) if camblib.is_file() else None
    ldd_pass = bool(
        ldd
        and ldd.returncode == 0
        and "not found" not in ldd.stdout
        and "not found" not in ldd.stderr
    )

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
        line.strip() for line in mpi.stdout.splitlines() if line.strip()
    )
    mpi_pass = (
        mpi.returncode == 0
        and len(mpi_lines) == EXPECTED_MPI_SIZE
        and all("size=4" in line for line in mpi_lines)
    )

    checksum_groups = {
        "resume_seed": checksum(
            ROOT / "results/provenance/mcmc-extension-seed-checksums.txt",
            ROOT,
        ),
        "released_chains": checksum(
            Path("checksums.txt"),
            ROOT / "data/derived",
        ),
        "raw_data": checksum(ROOT / "data/raw/checksums.txt", ROOT),
    }

    packages_path = Path(
        os.environ.get(
            "COBAYA_PACKAGES_PATH",
            "/opt/cobaya-packages-act-dr6",
        )
    ).resolve()

    checks = {
        "branch_matches": branch == EXPECTED_BRANCH,
        "bootstrap_commit_is_ancestor": bootstrap_is_ancestor,
        "environment_inputs_unchanged_since_bootstrap": (
            not critical_changes_since_bootstrap
        ),
        "tracked_worktree_clean": status == "",
        "python_3_11": platform.python_version().startswith("3.11."),
        "package_versions_match": all(
            versions[name] == wanted for name, wanted in EXPECTED.items()
        ),
        "act_lite_commit_matches": actual_act == expected_act,
        "bootstrap_records_cosmorec_build": bool(
            bootstrap_build.get("capability_verified")
        ),
        "camb_metadata_version_matches": (
            camb_record["metadata_version"] == EXPECTED["camb"]
        ),
        "camb_module_version_matches": (
            camb_record["module_version"] == EXPECTED["camb"]
        ),
        "camb_module_inside_pinned_source": camb_record[
            "module_inside_expected_source"
        ],
        "camb_editable_source_record_matches": (
            camb_record["direct_url_source_matches"]
            and camb_record["editable_installation"]
        ),
        "camb_cosmorec_class_available": camb_record[
            "cosmorec_class_available"
        ],
        "camb_commit_matches": camb_commit == EXPECTED_CAMB_COMMIT,
        "camb_tag_matches": camb_tag == EXPECTED["camb"],
        "forutils_commit_matches": (
            forutils_commit == EXPECTED_FORUTILS_COMMIT
        ),
        "cosmorec_archive_exists": cosmorec_archive.is_file(),
        "cosmorec_archive_sha256_matches": (
            cosmorec_archive.is_file()
            and sha256(cosmorec_archive)
            == EXPECTED_COSMOREC_ARCHIVE_SHA256
        ),
        "cosmorec_static_library_exists": cosmorec_lib.is_file(),
        "cosmorec_fpic_assignment_present": cosmorec_fpic_assignment,
        "camb_makefile_enables_cosmorec": camb_makefile_cosmorec,
        "camb_shared_library_exists": camblib.is_file(),
        "camb_linked_libraries_resolved": ldd_pass,
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
            "bootstrap_head": bootstrap_head,
            "bootstrap_is_ancestor": bootstrap_is_ancestor,
            "changed_since_bootstrap": changed_since_bootstrap,
            "critical_changes_since_bootstrap": critical_changes_since_bootstrap,
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
        "camb_cosmorec": {
            **camb_record,
            "expected_camb_commit": EXPECTED_CAMB_COMMIT,
            "installed_camb_commit": camb_commit,
            "expected_forutils_commit": EXPECTED_FORUTILS_COMMIT,
            "installed_forutils_commit": forutils_commit,
            "camb_tag": camb_tag,
            "cosmorec_version": EXPECTED_COSMOREC_VERSION,
            "cosmorec_archive": str(cosmorec_archive),
            "cosmorec_archive_sha256": (
                sha256(cosmorec_archive)
                if cosmorec_archive.is_file()
                else None
            ),
            "cosmorec_source": str(cosmorec_source),
            "cosmorec_static_library": str(cosmorec_lib),
            "cosmorec_fpic_assignment_present": cosmorec_fpic_assignment,
            "camb_makefile_enables_cosmorec": camb_makefile_cosmorec,
            "camb_shared_library": str(camblib),
            "ldd_returncode": ldd.returncode if ldd else None,
            "ldd_stdout": ldd.stdout.splitlines() if ldd else [],
            "ldd_stderr": ldd.stderr.strip() if ldd else "",
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
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (OUTPUT / "REPORT.md").write_text(
        "# Cloud deployment verification\n\n"
        f"Overall status: **{'PASS' if report['overall_pass'] else 'FAIL'}**\n\n"
        "CAMB's package version and compile-time CosmoRec capability were "
        "verified independently. A stock CAMB wheel cannot pass this gate.\n\n"
        "No likelihood data were installed, no likelihood was evaluated, "
        "no MCMC was started, and no target statistic was computed.\n\n"
        "```json\n"
        + json.dumps(checks, indent=2, sort_keys=True)
        + "\n```\n",
        encoding="utf-8",
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
