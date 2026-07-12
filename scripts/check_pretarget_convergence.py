#!/usr/bin/env python3

from __future__ import annotations

import json
import re
import shutil
import sys
import tomllib
from pathlib import Path

import arviz as az
import numpy as np
from getdist import chains as getdist_chains
from getdist.mcsamples import MCSamples


STEMS = (
    "planck_lcdm_camb",
    "actlite_lcdm_camb",
    "p-actlite_lcdm_camb",
)

LOCK_PATH = Path("config/chain_ingestion_lock.toml")
SCHEMA_PATH = Path(
    "results/provenance/phase1_parameter_schema/"
    "parameter_schema.json"
)
CHAIN_BASE = Path("data/derived/act_dr6_02/chains")
OUTPUT = Path(
    "results/provenance/"
    "phase1_pretarget_convergence"
)


def read_header(path: Path) -> list[str]:
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.startswith("#"):
                return line.lstrip("#").split()
            if line.strip():
                break

    raise RuntimeError(f"No header found in {path}")


def find_chain_files(stem: str) -> list[Path]:
    pattern = re.compile(
        rf"^{re.escape(stem)}\.(\d+)\.txt$"
    )
    found = []

    for path in (CHAIN_BASE / stem).rglob(
        f"{stem}.*.txt"
    ):
        match = pattern.match(path.name)
        if match:
            found.append((int(match.group(1)), path))

    return [
        path
        for _, path in sorted(found)
    ]


def load_retained_chain(
    path: Path,
    sampled_names: list[str],
    burn_fraction: float,
):
    columns = read_header(path)
    index = {
        name: position
        for position, name in enumerate(columns)
    }

    required = [
        "weight",
        "minuslogpost",
        *sampled_names,
    ]

    missing = [
        name
        for name in required
        if name not in index
    ]

    if missing:
        raise RuntimeError(
            f"{path}: missing columns {missing}"
        )

    data = np.loadtxt(
        path,
        comments="#",
        dtype=np.float64,
    )

    if data.ndim == 1:
        data = data.reshape(1, -1)

    if data.shape[1] != len(columns):
        raise RuntimeError(
            f"{path}: header/data column mismatch"
        )

    original_rows = data.shape[0]

    # Exact GetDist 1.7.7 fractional-row rule.
    removed_rows = int(
        round(original_rows * burn_fraction)
    )

    retained = data[removed_rows:, :]

    if retained.shape[0] == 0:
        raise RuntimeError(
            f"{path}: burn-in removed all rows"
        )

    if not np.all(np.isfinite(retained)):
        raise RuntimeError(
            f"{path}: retained data are not finite"
        )

    weights = retained[:, index["weight"]]

    if not np.all(weights > 0):
        raise RuntimeError(
            f"{path}: non-positive retained weights"
        )

    rounded_weights = np.rint(weights)
    integer_error = float(
        np.max(
            np.abs(
                weights - rounded_weights
            )
        )
    )

    samples = retained[
        :,
        [
            index[name]
            for name in sampled_names
        ],
    ]

    minuslogpost = retained[
        :,
        index["minuslogpost"],
    ]

    return {
        "path": str(path),
        "original_rows": int(original_rows),
        "removed_rows": int(removed_rows),
        "retained_rows": int(retained.shape[0]),
        "weights": weights,
        "integer_weights": (
            rounded_weights.astype(np.int64)
        ),
        "samples": samples,
        "minuslogpost": minuslogpost,
        "integer_error": integer_error,
    }


def scalar_dict(dataset, names):
    return {
        name: float(
            np.asarray(
                dataset[name].values
            ).squeeze()
        )
        for name in names
    }


def audit_dataset(
    stem: str,
    sampled_names: list[str],
    config,
):
    paths = find_chain_files(stem)

    if len(paths) != 4:
        raise RuntimeError(
            f"{stem}: expected 4 chain files, "
            f"found {len(paths)}"
        )

    burn_fraction = float(
        config["ingestion"][
            "primary_ignore_rows_fraction"
        ]
    )

    chains = [
        load_retained_chain(
            path,
            sampled_names,
            burn_fraction,
        )
        for path in paths
    ]

    integer_tolerance = 1e-12

    integer_weights_pass = all(
        chain["integer_error"]
        <= integer_tolerance
        for chain in chains
    )

    if not integer_weights_pass:
        raise RuntimeError(
            f"{stem}: weights are not integer "
            f"within {integer_tolerance}"
        )

    # Weighted multivariate GetDist diagnostic.
    getdist_chains.print_load_details = False

    samples = MCSamples(
        samples=[
            chain["samples"]
            for chain in chains
        ],
        weights=[
            chain["weights"]
            for chain in chains
        ],
        loglikes=[
            chain["minuslogpost"]
            for chain in chains
        ],
        names=sampled_names,
        labels=sampled_names,
        sampler="mcmc",
        ignore_rows=0,
    )

    getdist_rminus1 = float(
        samples.getGelmanRubin()
    )

    eigenvalues = [
        float(value)
        for value in np.asarray(
            samples.getGelmanRubinEigenvalues()
        ).reshape(-1)
    ]

    # Reconstruct the original draw multiplicities for
    # rank-normalized ArviZ diagnostics.
    expanded_chains = []
    expanded_lengths = []

    for chain in chains:
        expanded_count = int(
            chain["integer_weights"].sum()
        )

        if expanded_count > 10_000_000:
            raise RuntimeError(
                f"{stem}: expanded chain would "
                f"contain {expanded_count} draws"
            )

        expanded = np.repeat(
            chain["samples"],
            chain["integer_weights"],
            axis=0,
        )

        expanded_chains.append(expanded)
        expanded_lengths.append(
            int(expanded.shape[0])
        )

    aligned_draws = min(expanded_lengths)

    aligned = np.stack(
        [
            chain[-aligned_draws:, :]
            for chain in expanded_chains
        ],
        axis=0,
    )

    posterior = az.from_dict(
        posterior={
            name: aligned[:, :, position]
            for position, name
            in enumerate(sampled_names)
        }
    )

    rank_rhat = scalar_dict(
        az.rhat(
            posterior,
            var_names=sampled_names,
            method="rank",
        ),
        sampled_names,
    )

    bulk_ess = scalar_dict(
        az.ess(
            posterior,
            var_names=sampled_names,
            method="bulk",
        ),
        sampled_names,
    )

    tail_ess = scalar_dict(
        az.ess(
            posterior,
            var_names=sampled_names,
            method="tail",
        ),
        sampled_names,
    )

    total_weight = sum(
        float(chain["weights"].sum())
        for chain in chains
    )

    total_weight_squared = sum(
        float(
            np.square(
                chain["weights"]
            ).sum()
        )
        for chain in chains
    )

    retained_weight_ess = (
        total_weight ** 2
        / total_weight_squared
    )

    max_rhat_name = max(
        rank_rhat,
        key=rank_rhat.get,
    )

    min_bulk_name = min(
        bulk_ess,
        key=bulk_ess.get,
    )

    min_tail_name = min(
        tail_ess,
        key=tail_ess.get,
    )

    checks = {
        "four_numbered_chains":
            len(chains) == 4,

        "integer_weights":
            integer_weights_pass,

        "minimum_retained_weight_ess":
            retained_weight_ess
            >= config["convergence"][
                "minimum_retained_weight_ess"
            ],

        "getdist_multivariate_R_minus_1":
            getdist_rminus1
            <= config["convergence"][
                "weighted_multivariate_R_minus_1_max"
            ],

        "rank_normalized_split_rhat":
            max(rank_rhat.values())
            <= config["convergence"][
                "rank_normalized_split_rhat_max"
            ],

        "no_target_statistic_computed":
            True,
    }

    return {
        "stem": stem,
        "burn_fraction": burn_fraction,
        "sampled_parameters": sampled_names,
        "chain_rows": [
            {
                "path": chain["path"],
                "original_rows":
                    chain["original_rows"],
                "removed_rows":
                    chain["removed_rows"],
                "retained_rows":
                    chain["retained_rows"],
                "max_integer_error":
                    chain["integer_error"],
            }
            for chain in chains
        ],
        "expanded_draw_lengths":
            expanded_lengths,
        "aligned_draws_per_chain":
            aligned_draws,
        "retained_weight_ess":
            retained_weight_ess,
        "getdist": {
            "multivariate_R_minus_1":
                getdist_rminus1,
            "eigenvalues":
                eigenvalues,
        },
        "arviz": {
            "rank_rhat":
                rank_rhat,
            "bulk_ess":
                bulk_ess,
            "tail_ess":
                tail_ess,
            "maximum_rank_rhat": {
                "parameter":
                    max_rhat_name,
                "value":
                    rank_rhat[
                        max_rhat_name
                    ],
            },
            "minimum_bulk_ess": {
                "parameter":
                    min_bulk_name,
                "value":
                    bulk_ess[
                        min_bulk_name
                    ],
            },
            "minimum_tail_ess": {
                "parameter":
                    min_tail_name,
                "value":
                    tail_ess[
                        min_tail_name
                    ],
            },
        },
        "checks": checks,
        "pass": all(checks.values()),
    }


def main():
    if OUTPUT.exists():
        raise SystemExit(
            f"{OUTPUT} already exists. "
            "Remove it deliberately before rerunning."
        )

    OUTPUT.mkdir(parents=True)

    with LOCK_PATH.open("rb") as handle:
        config = tomllib.load(handle)

    schema = json.loads(
        SCHEMA_PATH.read_text(
            encoding="utf-8"
        )
    )

    results = []
    errors = []

    for stem in STEMS:
        try:
            sampled_names = list(
                schema[stem][
                    "parameters"
                ]["sampled"].keys()
            )

            results.append(
                audit_dataset(
                    stem,
                    sampled_names,
                    config,
                )
            )

        except Exception as exc:
            errors.append(
                f"{stem}: "
                f"{type(exc).__name__}: "
                f"{exc}"
            )

    checks = {
        "all_three_datasets_completed":
            len(results) == 3,

        "all_datasets_pass":
            len(results) == 3
            and all(
                result["pass"]
                for result in results
            ),

        "no_runtime_errors":
            not errors,

        "no_target_statistic_computed":
            True,
    }

    summary = {
        "phase":
            "pre-target convergence gate",
        "datasets":
            results,
        "errors":
            errors,
        "checks":
            checks,
        "overall_pass":
            all(checks.values()),
    }

    output = (
        OUTPUT
        / "convergence_diagnostics.json"
    )

    output.write_text(
        json.dumps(
            summary,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    print(
        "Overall pass:",
        summary["overall_pass"],
    )

    for result in results:
        print()
        print(result["stem"])
        print(
            "  retained weight ESS:",
            result["retained_weight_ess"],
        )
        print(
            "  GetDist R-1:",
            result["getdist"][
                "multivariate_R_minus_1"
            ],
        )
        print(
            "  max rank R-hat:",
            result["arviz"][
                "maximum_rank_rhat"
            ],
        )
        print(
            "  min bulk ESS:",
            result["arviz"][
                "minimum_bulk_ess"
            ],
        )
        print(
            "  min tail ESS:",
            result["arviz"][
                "minimum_tail_ess"
            ],
        )
        print(
            "  checks:",
            result["checks"],
        )

    print()
    print("Errors:", errors or "none")
    print("Output:", output)

    return (
        0
        if summary["overall_pass"]
        else 1
    )


if __name__ == "__main__":
    raise SystemExit(main())
