#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import math
import os
import platform
import statistics
import time
from concurrent.futures import ProcessPoolExecutor
from importlib.metadata import version
from pathlib import Path

# Prevent thread oversubscription inside worker processes.
os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")

import camb


NOMINAL = {
    "H0": 67.0,
    "ombh2": 0.022,
    "omch2": 0.120,
    "tau": 0.055,
}


def calculate_background(point):
    H0, ombh2, omch2, tau = point

    pars = camb.CAMBparams()

    pars.set_cosmology(
        H0=H0,
        ombh2=ombh2,
        omch2=omch2,
        omk=0.0,
        mnu=0.06,
        nnu=3.044,
        num_massive_neutrinos=1,
        neutrino_hierarchy="degenerate",
        TCMB=2.7255,
        tau=tau,
    )

    pars.set_dark_energy(
        w=-1.0,
        wa=0.0,
        dark_energy_model="fluid",
    )

    # No spectra or thermodynamic/recombination calculation is required.
    background = camb.get_background(
        pars,
        no_thermo=True,
    )

    components = {
        "baryon": float(
            background.get_Omega("baryon", 0.0)
        ),
        "cdm": float(
            background.get_Omega("cdm", 0.0)
        ),
        "massive_neutrino": float(
            background.get_Omega("nu", 0.0)
        ),
        "photon": float(
            background.get_Omega("photon", 0.0)
        ),
        "massless_neutrino": float(
            background.get_Omega("neutrino", 0.0)
        ),
        "dark_energy": float(
            background.get_Omega("de", 0.0)
        ),
        "curvature": float(
            background.get_Omega("K", 0.0)
        ),
    }

    omega_m = (
        components["baryon"]
        + components["cdm"]
        + components["massive_neutrino"]
    )

    closure = sum(components.values())

    return {
        "age_Gyr": float(
            background.physical_time(0.0)
        ),
        "Omega_m": omega_m,
        "Omega_Lambda": components["dark_energy"],
        "closure_sum": closure,
        "components": components,
    }


def synthetic_points(count):
    points = []

    for index in range(count):
        fraction = index / max(count - 1, 1)

        H0 = 60.0 + 15.0 * fraction

        ombh2 = (
            0.020
            + 0.004
            * ((7 * index) % count)
            / max(count - 1, 1)
        )

        omch2 = (
            0.100
            + 0.040
            * ((13 * index) % count)
            / max(count - 1, 1)
        )

        tau = (
            0.040
            + 0.040
            * ((17 * index) % count)
            / max(count - 1, 1)
        )

        points.append(
            (H0, ombh2, omch2, tau)
        )

    return points


def relative_difference(left, right):
    denominator = max(
        abs(left),
        abs(right),
        1.0,
    )

    return abs(left - right) / denominator


def compare_results(left, right):
    fields = (
        "age_Gyr",
        "Omega_m",
        "Omega_Lambda",
        "closure_sum",
    )

    return max(
        relative_difference(
            left[field],
            right[field],
        )
        for field in fields
    )


def percentile(values, probability):
    ordered = sorted(values)
    position = (
        probability
        * (len(ordered) - 1)
    )

    lower = math.floor(position)
    upper = math.ceil(position)

    if lower == upper:
        return ordered[lower]

    weight = position - lower

    return (
        ordered[lower] * (1.0 - weight)
        + ordered[upper] * weight
    )


def main():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--workers",
        type=int,
        default=min(
            2,
            os.cpu_count() or 1,
        ),
    )

    parser.add_argument(
        "--output",
        type=Path,
        default=Path(
            "results/provenance/"
            "phase1_camb_background_benchmark/"
            "benchmark.json"
        ),
    )

    args = parser.parse_args()

    if version("camb") != "1.5.0":
        raise SystemExit(
            "This benchmark requires CAMB 1.5.0"
        )

    nominal_point = (
        NOMINAL["H0"],
        NOMINAL["ombh2"],
        NOMINAL["omch2"],
        NOMINAL["tau"],
    )

    # Five unrecorded warm-up calls.
    for _ in range(5):
        calculate_background(nominal_point)

    timing_seconds = []

    for _ in range(100):
        start = time.perf_counter()
        calculate_background(nominal_point)
        timing_seconds.append(
            time.perf_counter() - start
        )

    repeatability = [
        calculate_background(nominal_point)
        for _ in range(16)
    ]

    reference = repeatability[0]

    maximum_repeatability_difference = max(
        compare_results(reference, result)
        for result in repeatability[1:]
    )

    points = synthetic_points(32)

    serial_start = time.perf_counter()

    serial_results = [
        calculate_background(point)
        for point in points
    ]

    serial_seconds = (
        time.perf_counter()
        - serial_start
    )

    parallel_start = time.perf_counter()

    with ProcessPoolExecutor(
        max_workers=args.workers
    ) as executor:
        parallel_results = list(
            executor.map(
                calculate_background,
                points,
            )
        )

    parallel_seconds = (
        time.perf_counter()
        - parallel_start
    )

    maximum_serial_parallel_difference = max(
        compare_results(serial, parallel)
        for serial, parallel
        in zip(
            serial_results,
            parallel_results,
            strict=True,
        )
    )

    maximum_closure_error = max(
        abs(
            result["closure_sum"]
            - 1.0
        )
        for result in serial_results
    )

    tolerance = 1e-12

    checks = {
        "camb_version_1_5_0":
            version("camb") == "1.5.0",

        "one_hundred_measured_calls":
            len(timing_seconds) == 100,

        "sixteen_repeatability_calls":
            len(repeatability) == 16,

        "thirty_two_serial_parallel_calls":
            len(points) == 32,

        "repeatability_within_tolerance":
            maximum_repeatability_difference
            <= tolerance,

        "serial_parallel_identity":
            maximum_serial_parallel_difference
            <= tolerance,

        "background_closure":
            maximum_closure_error
            <= 1e-10,

        "no_target_statistic_computed":
            True,
    }

    report = {
        "phase":
            "CAMB background timing and reproducibility",

        "software": {
            "python":
                platform.python_version(),
            "camb":
                version("camb"),
        },

        "machine": {
            "platform":
                platform.platform(),
            "logical_cpus":
                os.cpu_count(),
            "workers":
                args.workers,
        },

        "timing": {
            "measured_calls":
                len(timing_seconds),
            "median_seconds":
                statistics.median(
                    timing_seconds
                ),
            "mean_seconds":
                statistics.fmean(
                    timing_seconds
                ),
            "p90_seconds":
                percentile(
                    timing_seconds,
                    0.90,
                ),
            "minimum_seconds":
                min(timing_seconds),
            "maximum_seconds":
                max(timing_seconds),
        },

        "parallel_test": {
            "points":
                len(points),
            "serial_seconds":
                serial_seconds,
            "parallel_seconds":
                parallel_seconds,
            "speedup":
                (
                    serial_seconds
                    / parallel_seconds
                ),
            "maximum_relative_difference":
                maximum_serial_parallel_difference,
        },

        "repeatability": {
            "calls":
                len(repeatability),
            "maximum_relative_difference":
                maximum_repeatability_difference,
        },

        "maximum_closure_error":
            maximum_closure_error,

        "nominal_output_for_technical_validation":
            reference,

        "checks":
            checks,

        "overall_pass":
            all(checks.values()),
    }

    args.output.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    args.output.write_text(
        json.dumps(
            report,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    print(
        "Overall pass:",
        report["overall_pass"],
    )

    print(
        "Median seconds per background:",
        report["timing"]["median_seconds"],
    )

    print(
        "P90 seconds per background:",
        report["timing"]["p90_seconds"],
    )

    print(
        "Serial 32-call seconds:",
        serial_seconds,
    )

    print(
        "Parallel 32-call seconds:",
        parallel_seconds,
    )

    print(
        "Parallel speedup:",
        report["parallel_test"]["speedup"],
    )

    print(
        "Maximum repeatability difference:",
        maximum_repeatability_difference,
    )

    print(
        "Maximum serial/parallel difference:",
        maximum_serial_parallel_difference,
    )

    print(
        "Maximum closure error:",
        maximum_closure_error,
    )

    print(
        "No target statistic computed."
    )

    return (
        0
        if report["overall_pass"]
        else 1
    )


if __name__ == "__main__":
    raise SystemExit(main())
