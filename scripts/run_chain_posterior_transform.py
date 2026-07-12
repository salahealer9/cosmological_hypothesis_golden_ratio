#!/usr/bin/env python3
"""Run the v0.1.2 chain-only CAMB posterior transformation.

Commit this script before running it. Posterior summaries are emitted only after
all frozen derived-X convergence checks pass.

Implementation revision 2 fixes GetDist chain separation by preserving the
released minuslogpost arrays and enforces an all-datasets gate before output.
"""
from __future__ import annotations

import json
import math
import os
import re
import sys
import time
import tomllib
from importlib.metadata import version
from pathlib import Path

os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")

import arviz as az
import camb
import numpy as np
from getdist import chains as gd_chains
from getdist.mcsamples import MCSamples

LOCK = Path("config/chain_ingestion_lock.toml")
CHAIN_ROOT = Path("data/derived/act_dr6_02/chains")
OUT = Path("results/confirmatory/phase1_chain_only")
DERIVED = Path("data/derived/act_dr6_02/phase1_chain_only")
DATASETS = (
    ("planck", "planck_lcdm_camb"),
    ("actlite", "actlite_lcdm_camb"),
    ("planck_actlite", "p-actlite_lcdm_camb"),
)
FIELDS = (
    "age_Gyr", "Omega_m", "Omega_Lambda", "closure", "H0_t0", "X",
    "delta_Phi", "X_matter_lambda", "X_minus_matter_lambda",
)


def read_header(path: Path) -> list[str]:
    with path.open() as handle:
        for line in handle:
            if line.startswith("#"):
                return line.lstrip("#").split()
    raise RuntimeError(f"No header in {path}")


def chain_files(stem: str) -> list[Path]:
    pattern = re.compile(rf"^{re.escape(stem)}\.(\d+)\.txt$")
    found = []
    for path in (CHAIN_ROOT / stem).rglob(f"{stem}.*.txt"):
        match = pattern.match(path.name)
        if match:
            found.append((int(match.group(1)), path))
    return [path for _, path in sorted(found)]


def load_chain(path: Path) -> dict:
    names = read_header(path)
    index = {name: position for position, name in enumerate(names)}
    required = ("weight", "minuslogpost", "H0", "ombh2", "omch2", "tau")
    missing = [name for name in required if name not in index]
    if missing:
        raise RuntimeError(f"{path}: missing {missing}")
    data = np.loadtxt(path, comments="#", dtype=float)
    if data.ndim == 1:
        data = data.reshape(1, -1)
    if not np.all(np.isfinite(data)):
        raise RuntimeError(f"{path}: non-finite values")
    weights = data[:, index["weight"]]
    integer_weights = np.rint(weights).astype(np.int64)
    if not np.all(weights > 0):
        raise RuntimeError(f"{path}: non-positive weights")
    if np.max(np.abs(weights - integer_weights)) > 1e-12:
        raise RuntimeError(f"{path}: non-integer weights")
    return {
        "source": str(path), "rows": len(data), "weight": weights,
        "integer_weight": integer_weights,
        "minuslogpost": data[:, index["minuslogpost"]],
        "H0": data[:, index["H0"]],
        "ombh2": data[:, index["ombh2"]],
        "omch2": data[:, index["omch2"]], "tau": data[:, index["tau"]],
    }


def evaluate(H0, ombh2, omch2, tau, config) -> tuple[float, ...]:
    fixed = config["background"]["fixed_model"]
    units = config["dimensionless_age"]
    pars = camb.CAMBparams()
    pars.set_cosmology(
        H0=float(H0), ombh2=float(ombh2), omch2=float(omch2),
        omk=float(fixed["omk"]), mnu=float(fixed["mnu_eV"]),
        nnu=float(fixed["nnu"]),
        num_massive_neutrinos=int(fixed["num_massive_neutrinos"]),
        neutrino_hierarchy=str(fixed["neutrino_hierarchy"]),
        TCMB=float(fixed["TCMB_K"]), tau=float(tau),
    )
    pars.set_dark_energy(w=-1.0, wa=0.0, dark_energy_model="fluid")
    background = camb.get_background(pars, no_thermo=True)
    age = float(background.physical_time(0.0))
    omega_m = (
        float(background.get_Omega("baryon", 0.0))
        + float(background.get_Omega("cdm", 0.0))
        + float(background.get_Omega("nu", 0.0))
    )
    omega_lambda = float(background.get_Omega("de", 0.0))
    closure = (
        omega_m + omega_lambda
        + float(background.get_Omega("photon", 0.0))
        + float(background.get_Omega("neutrino", 0.0))
        + float(background.get_Omega("K", 0.0))
    )
    h0t0 = (
        float(H0) * 1000.0 / float(units["Mpc_in_metres"])
        * age * float(units["Gyr_in_seconds"])
    )
    x_value = h0t0 * math.sqrt(omega_lambda)
    target = float(units["target_value"])
    approximation = 2.0 / 3.0 * math.asinh(
        math.sqrt(omega_lambda / omega_m)
    )
    return (
        age, omega_m, omega_lambda, closure, h0t0, x_value,
        x_value - target, approximation, x_value - approximation,
    )


def transform(chain: dict, config: dict, stem: str, number: int) -> dict:
    output = np.empty((chain["rows"], len(FIELDS)))
    started = time.perf_counter()
    for row in range(chain["rows"]):
        output[row] = evaluate(
            chain["H0"][row], chain["ombh2"][row],
            chain["omch2"][row], chain["tau"][row], config,
        )
        if (row + 1) % 25000 == 0:
            print(f"{stem}.{number}: {row + 1}/{chain['rows']}", flush=True)
    result = dict(chain)
    for position, name in enumerate(FIELDS):
        result[name] = output[:, position]
    result["seconds"] = time.perf_counter() - started
    return result


def retained(chain: dict, fraction: float) -> slice:
    return slice(int(round(chain["rows"] * fraction)), chain["rows"])


def pool(chains: list[dict], field: str, fraction: float):
    return (
        np.concatenate([chain[field][retained(chain, fraction)] for chain in chains]),
        np.concatenate([chain["weight"][retained(chain, fraction)] for chain in chains]),
    )


def weighted_quantiles(values, weights, probabilities):
    order = np.argsort(values, kind="mergesort")
    values = values[order]
    weights = weights[order]
    cumulative = np.cumsum(weights)
    return {
        f"{probability:.3f}": float(values[min(
            np.searchsorted(cumulative, probability * cumulative[-1]),
            len(values) - 1,
        )])
        for probability in probabilities
    }


def weighted_summary(values, weights, probabilities):
    total = float(weights.sum())
    mean = float(np.sum(weights * values) / total)
    variance = float(np.sum(weights * (values - mean) ** 2) / total)
    return {
        "rows": len(values), "weight_sum": total, "mean": mean,
        "standard_deviation": math.sqrt(max(variance, 0.0)),
        "quantiles": weighted_quantiles(values, weights, probabilities),
        "minimum": float(values.min()), "maximum": float(values.max()),
    }


def convergence(chains: list[dict], config: dict) -> dict:
    fraction = float(config["ingestion"]["primary_ignore_rows_fraction"])
    xs = [chain["X"][retained(chain, fraction)] for chain in chains]
    weights = [chain["weight"][retained(chain, fraction)] for chain in chains]
    integer_weights = [
        chain["integer_weight"][retained(chain, fraction)] for chain in chains
    ]
    loglikes = [
        chain["minuslogpost"][retained(chain, fraction)] for chain in chains
    ]
    gd_chains.print_load_details = False
    samples = MCSamples(
        samples=[x[:, None] for x in xs],
        weights=weights,
        loglikes=loglikes,
        names=["X"], labels=["X"], sampler="mcmc", ignore_rows=0,
    )
    rminus1 = float(samples.getGelmanRubin())
    expanded = [
        np.repeat(x, multiplicity)
        for x, multiplicity in zip(xs, integer_weights, strict=True)
    ]
    aligned_draws = min(map(len, expanded))
    aligned = np.stack([x[-aligned_draws:] for x in expanded])
    inference = az.from_dict(posterior={"X": aligned})
    rhat = float(np.asarray(az.rhat(inference, method="rank")["X"]).squeeze())
    bulk = float(np.asarray(az.ess(inference, method="bulk")["X"]).squeeze())
    tail = float(np.asarray(az.ess(inference, method="tail")["X"]).squeeze())
    checks = {
        "getdist_R_minus_1": rminus1 <= 0.01,
        "rank_Rhat": rhat <= 1.01,
        "bulk_ESS_X": bulk >= 10000,
        "tail_ESS_X": tail >= 10000,
    }
    return {
        "getdist_R_minus_1": rminus1, "rank_Rhat": rhat,
        "bulk_ESS_X": bulk, "tail_ESS_X": tail,
        "expanded_lengths": [len(x) for x in expanded],
        "aligned_draws_per_chain": aligned_draws,
        "checks": checks, "pass": all(checks.values()),
    }


def technical_validation(chains: list[dict], config: dict) -> dict:
    fraction = float(config["ingestion"]["primary_ignore_rows_fraction"])
    closure, _ = pool(chains, "closure", fraction)
    age, _ = pool(chains, "age_Gyr", fraction)
    omega_lambda, _ = pool(chains, "Omega_Lambda", fraction)
    checks = {
        "closure": float(np.max(np.abs(closure - 1.0))) <= 1e-10,
        "positive_age": bool(np.all(age > 0)),
        "physical_Omega_Lambda": bool(np.all(
            (omega_lambda > 0) & (omega_lambda < 1)
        )),
    }
    return {
        "maximum_closure_error": float(np.max(np.abs(closure - 1.0))),
        "checks": checks, "pass": all(checks.values()),
    }


def compare_target(values, weights, target, probabilities):
    delta = values - target
    summary = weighted_summary(delta, weights, probabilities)
    return {
        "target": target, "delta": summary,
        "probability_X_above": float(weights[values > target].sum() / weights.sum()),
        "probability_X_below": float(weights[values < target].sum() / weights.sum()),
        "absolute_mean_distance_in_sd": (
            abs(summary["mean"]) / summary["standard_deviation"]
            if summary["standard_deviation"] else math.inf
        ),
    }


def save_arrays(stem: str, chains: list[dict]) -> list[str]:
    DERIVED.mkdir(parents=True, exist_ok=True)
    paths = []
    for number, chain in enumerate(chains, 1):
        path = DERIVED / f"{stem}.{number}.npz"
        np.savez_compressed(
            path, source=np.array(chain["source"]), weight=chain["weight"],
            integer_weight=chain["integer_weight"],
            minuslogpost=chain["minuslogpost"], H0=chain["H0"],
            ombh2=chain["ombh2"], omch2=chain["omch2"], tau=chain["tau"],
            **{name: chain[name] for name in FIELDS},
        )
        paths.append(str(path))
    return paths


def posterior_record(
    key: str,
    stem: str,
    chains: list[dict],
    config: dict,
    probabilities: list[float],
) -> dict:
    """Build target-bearing outputs only after every dataset gate passes."""
    primary_fraction = float(
        config["ingestion"]["primary_ignore_rows_fraction"]
    )
    x_values, weights = pool(chains, "X", primary_fraction)
    target = float(config["dimensionless_age"]["target_value"])
    fractions = sorted(set([
        primary_fraction,
        *map(float, config["ingestion"]["burnin_sensitivity_fractions"]),
    ]))

    record = {
        "dataset_key": key,
        "stem": stem,
        "role": config["chains"][key]["role"],
        "posterior_summary": {
            "X": weighted_summary(x_values, weights, probabilities),
            "Phi_target": compare_target(
                x_values, weights, target, probabilities
            ),
            "burnin_sensitivity_X": {
                f"{fraction:.2f}": weighted_summary(
                    *pool(chains, "X", fraction), probabilities
                )
                for fraction in fractions
            },
            "per_chain_X": [
                weighted_summary(
                    chain["X"][retained(chain, primary_fraction)],
                    chain["weight"][retained(chain, primary_fraction)],
                    probabilities,
                )
                for chain in chains
            ],
        },
        "negative_controls": {
            item["name"]: compare_target(
                x_values, weights, float(item["value"]), probabilities
            )
            for item in config["posterior_outputs"]["negative_controls"]
        },
    }
    approximation, approximation_weights = pool(
        chains, "X_minus_matter_lambda", primary_fraction
    )
    record["matter_lambda_crosscheck"] = weighted_summary(
        approximation, approximation_weights, probabilities
    )
    record["derived_files"] = save_arrays(stem, chains)
    return record


def main() -> int:
    if OUT.exists() or DERIVED.exists():
        raise SystemExit("Output already exists; refusing to overwrite.")
    if version("camb") != "1.5.0" or version("arviz") != "0.23.4":
        raise SystemExit("Requires CAMB 1.5.0 and ArviZ 0.23.4.")
    with LOCK.open("rb") as handle:
        config = tomllib.load(handle)

    probabilities = [
        float(value)
        for value in config["posterior_outputs"]["weighted_quantiles"]
    ]
    transformed_datasets = []
    gate_records = []
    started = time.perf_counter()

    # Stage 1: transform and evaluate every frozen technical/convergence gate.
    # No posterior target summary or derived file is written in this stage.
    for key, stem in DATASETS:
        paths = chain_files(stem)
        if len(paths) != 4:
            raise RuntimeError(f"{stem}: found {len(paths)} chains, expected 4")
        print(f"\n=== {stem} ===", flush=True)
        chains = [
            transform(load_chain(path), config, stem, number)
            for number, path in enumerate(paths, 1)
        ]
        validation = technical_validation(chains, config)
        x_gate = convergence(chains, config)
        passed = validation["pass"] and x_gate["pass"]
        gate_records.append({
            "dataset_key": key,
            "stem": stem,
            "role": config["chains"][key]["role"],
            "technical_validation": validation,
            "derived_X_convergence": x_gate,
            "transform_seconds": sum(chain["seconds"] for chain in chains),
            "pass": passed,
        })
        transformed_datasets.append((key, stem, chains))

    all_gates_pass = all(record["pass"] for record in gate_records)

    if not all_gates_pass:
        # Technical-only failure record. It contains no posterior target values.
        OUT.mkdir(parents=True)
        failure = {
            "phase": "chain-only posterior transformation technical gate",
            "lock": str(LOCK),
            "datasets": gate_records,
            "wall_seconds": time.perf_counter() - started,
            "overall_pass": False,
            "posterior_target_output_released": False,
        }
        output = OUT / "technical_gate_failure.json"
        output.write_text(
            json.dumps(failure, indent=2, sort_keys=True) + "\n"
        )
        print("\nAt least one derived-X gate failed.")
        print("No posterior target summary or derived arrays were written.")
        print(f"Technical output: {output}")
        return 1

    # Stage 2: every dataset passed, so target-bearing summaries may be built.
    OUT.mkdir(parents=True)
    results = []
    for gate_record, (key, stem, chains) in zip(
        gate_records, transformed_datasets, strict=True
    ):
        record = dict(gate_record)
        record.update(
            posterior_record(key, stem, chains, config, probabilities)
        )
        results.append(record)

    report = {
        "phase": "chain-only posterior transformation",
        "lock": str(LOCK),
        "software": {
            "camb": version("camb"),
            "arviz": version("arviz"),
            "getdist": version("getdist"),
            "numpy": version("numpy"),
        },
        "datasets": results,
        "wall_seconds": time.perf_counter() - started,
        "overall_pass": True,
        "posterior_target_output_released": True,
        "interpretation_boundary": (
            "Descriptive M0 posterior analysis only; this does not replace "
            "the frozen held-out predictive or evidence calculations."
        ),
    }
    output = OUT / "summary.json"
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print("\nOverall pass: True")
    print(f"Output: {output}")
    print(f"Wall seconds: {report['wall_seconds']:.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
