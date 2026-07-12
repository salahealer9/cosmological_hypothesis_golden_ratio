#!/usr/bin/env python3
"""
Cobaya -> PolyChord wrapper smoke test.

Uses a normalized Gaussian likelihood and a bounded internal Cobaya prior.
No cosmological data are used.

Run from the repository root:

    mpirun -np 2 python scripts/cobaya_polychord_smoke_test.py
"""

from __future__ import annotations

import json
import math
import shutil
import sys
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

import numpy as np
from mpi4py import MPI
from scipy.special import ndtr

from cobaya.run import run


LOWER = -10.0
UPPER = 10.0
OUTPUT_PREFIX = Path("results/cobaya_smoke/cobaya_gaussian")
SEED = 20260712


def gaussian_like(theta: float) -> float:
    """Normalized N(theta | 0, 1) log-likelihood."""
    return -0.5 * theta * theta - 0.5 * math.log(2.0 * math.pi)


def package_version(name: str) -> str:
    try:
        return version(name)
    except PackageNotFoundError:
        return "not-installed"


def analytic_log_evidence() -> float:
    mass = float(ndtr(UPPER) - ndtr(LOWER))
    return -math.log(UPPER - LOWER) + math.log(mass)


def scalar(value) -> float:
    arr = np.asarray(value)
    if arr.size != 1:
        raise ValueError(f"Expected scalar, got shape {arr.shape}")
    return float(arr.reshape(-1)[0])


def main() -> int:
    comm = MPI.COMM_WORLD
    rank = comm.Get_rank()

    output_dir = OUTPUT_PREFIX.parent.resolve()
    if rank == 0:
        if output_dir.exists():
            shutil.rmtree(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
    comm.Barrier()

    info = {
        "likelihood": {
            "gaussian": {
                "external": gaussian_like,
            }
        },
        "params": {
            "theta": {
                "prior": {"min": LOWER, "max": UPPER},
                "ref": {"dist": "norm", "loc": 0.0, "scale": 1.0},
                "proposal": 1.0,
                "latex": r"\theta",
            }
        },
        "sampler": {
            "polychord": {
                "path": "global",
                "nlive": 50,
                "num_repeats": 5,
                "nprior": "5nlive",
                "precision_criterion": 0.1,
                "do_clustering": False,
                "seed": SEED,
                "feedback": 1,
                "read_resume": False,
                "write_resume": True,
                "write_stats": True,
                "write_live": True,
                "write_dead": True,
                "write_prior": True,
            }
        },
        "output": str(OUTPUT_PREFIX),
        "force": True,
        "debug": False,
    }

    updated_info, sampler = run(info)

    if rank != 0:
        return 0

    logz = scalar(sampler.logZ)
    logzerr = abs(scalar(sampler.logZstd))
    exact = analytic_log_evidence()
    absolute_error = abs(logz - exact)
    tolerance = max(0.25, 3.0 * logzerr)

    sample = sampler.samples(combined=False)
    sample_rows = 0 if sample is None else len(sample)

    expected_files = [
        Path(f"{OUTPUT_PREFIX}.input.yaml"),
        Path(f"{OUTPUT_PREFIX}.updated.yaml"),
    ]
    existing_expected_files = [str(path) for path in expected_files if path.exists()]
    raw_dir = Path(f"{OUTPUT_PREFIX}_polychord_raw")

    checks = {
        "finite_logZ": math.isfinite(logz),
        "finite_logZ_error": math.isfinite(logzerr) and logzerr > 0.0,
        "analytic_evidence_agreement": absolute_error <= tolerance,
        "posterior_sample_nonempty": sample_rows > 0,
        "cobaya_metadata_written": len(existing_expected_files) >= 1,
        "polychord_raw_output_written": raw_dir.exists(),
    }
    passed = all(checks.values())

    summary = {
        "test": "Cobaya-to-PolyChord wrapper smoke test",
        "software": {
            "python": sys.version.split()[0],
            "cobaya": package_version("cobaya"),
            "pypolychord": package_version("pypolychord"),
            "mpi4py": package_version("mpi4py"),
            "numpy": package_version("numpy"),
            "scipy": package_version("scipy"),
        },
        "mpi_size": comm.Get_size(),
        "seed": SEED,
        "prior": {"distribution": "uniform", "lower": LOWER, "upper": UPPER},
        "numerical_logZ": logz,
        "reported_logZ_error": logzerr,
        "analytic_logZ": exact,
        "absolute_error": absolute_error,
        "acceptance_tolerance": tolerance,
        "posterior_sample_rows": sample_rows,
        "metadata_files": existing_expected_files,
        "raw_output_directory": str(raw_dir),
        "checks": checks,
        "overall_pass": passed,
    }

    summary_path = output_dir / "summary.json"
    report_path = output_dir / "REPORT.md"
    summary_path.write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    report_path.write_text(
        f"""# Cobaya-to-PolyChord wrapper smoke test

Overall status: **{"PASS" if passed else "FAIL"}**

- Numerical log evidence: `{logz:.9f}`
- Reported uncertainty: `{logzerr:.9f}`
- Analytic log evidence: `{exact:.9f}`
- Absolute error: `{absolute_error:.9f}`
- Acceptance tolerance: `{tolerance:.9f}`
- Posterior rows: `{sample_rows}`
- MPI processes: `{comm.Get_size()}`

## Checks

```json
{json.dumps(checks, indent=2, sort_keys=True)}
```
""",
        encoding="utf-8",
    )

    print(f"Numerical logZ: {logz:+.9f} +/- {logzerr:.9f}")
    print(f"Analytic logZ:  {exact:+.9f}")
    print(f"Absolute error: {absolute_error:.9f}")
    print(f"Summary:        {summary_path}")
    print(f"Overall:        {'PASS' if passed else 'FAIL'}")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
