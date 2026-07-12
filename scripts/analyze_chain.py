#!/usr/bin/env python3
"""Compute the golden-ratio diagnostic from a CSV posterior chain."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from golden_ratio_cosmology.core import GOLDEN_TARGET
from golden_ratio_cosmology.posterior import summarize_x, x_from_density_samples

MPC_KM = 3.0856775814913673e19
SECONDS_PER_GYR = 365.25 * 86400.0 * 1.0e9


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--omega-m-column", required=True)
    parser.add_argument("--omega-de-column", required=True)
    parser.add_argument("--weight-column")
    parser.add_argument("--omega-r-column")
    parser.add_argument("--omega-k-column")
    parser.add_argument("--w0-column")
    parser.add_argument("--wa-column")
    parser.add_argument("--h0-column", help="H0 in km s^-1 Mpc^-1")
    parser.add_argument("--age-gyr-column", help="Cosmic age in Gyr")
    parser.add_argument("--epsilon", type=float, default=0.005)
    return parser.parse_args()


def optional_column(df: pd.DataFrame, name: str | None) -> np.ndarray | None:
    return None if name is None else df[name].to_numpy(dtype=float)


def main() -> None:
    args = parse_args()
    df = pd.read_csv(args.input)
    weights = np.ones(len(df), dtype=float) if args.weight_column is None else df[args.weight_column].to_numpy(dtype=float)

    if (args.h0_column is None) ^ (args.age_gyr_column is None):
        raise SystemExit("Supply both --h0-column and --age-gyr-column, or neither.")

    omega_de = df[args.omega_de_column].to_numpy(dtype=float)
    if args.h0_column and args.age_gyr_column:
        h0_si = df[args.h0_column].to_numpy(dtype=float) / MPC_KM
        age_seconds = df[args.age_gyr_column].to_numpy(dtype=float) * SECONDS_PER_GYR
        x = h0_si * age_seconds * np.sqrt(omega_de)
        computation = "direct_from_H0_and_age"
    else:
        x = x_from_density_samples(
            omega_m=df[args.omega_m_column].to_numpy(dtype=float),
            omega_de=omega_de,
            omega_r=optional_column(df, args.omega_r_column),
            omega_k=optional_column(df, args.omega_k_column),
            w0=optional_column(df, args.w0_column),
            wa=optional_column(df, args.wa_column),
        )
        computation = "background_age_integral"

    summary = summarize_x(x, weights=weights, epsilon=args.epsilon).as_dict()
    payload = {
        "input": str(args.input),
        "computation": computation,
        "golden_target": GOLDEN_TARGET,
        "summary": summary,
        "interpretation_warning": (
            "This posterior diagnostic is not by itself a confirmatory p-value or a physical derivation. "
            "Use the preregistered model-comparison and held-out-data protocol."
        ),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
