"""Posterior-sample diagnostics.

This module does not claim a classical p-value from a posterior chain.  It
summarizes the posterior distribution of the predeclared residual
Delta_Phi = X - Phi^(-1/2), retaining supplied sample weights.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import numpy as np

from .core import GOLDEN_TARGET, CosmologyParameters, diagnostic_x


@dataclass(frozen=True)
class PosteriorSummary:
    n_samples: int
    effective_sample_size: float
    mean_x: float
    std_x: float
    median_x: float
    q025_x: float
    q975_x: float
    mean_delta: float
    std_delta: float
    posterior_mass_delta_positive: float
    posterior_mass_abs_delta_below_epsilon: float
    epsilon: float

    def as_dict(self) -> dict[str, float | int]:
        return self.__dict__.copy()


def normalize_weights(weights: np.ndarray) -> np.ndarray:
    weights = np.asarray(weights, dtype=float)
    if weights.ndim != 1:
        raise ValueError("weights must be one-dimensional")
    if not np.all(np.isfinite(weights)) or np.any(weights < 0):
        raise ValueError("weights must be finite and non-negative")
    total = weights.sum()
    if total <= 0:
        raise ValueError("weights must have a positive sum")
    return weights / total


def weighted_quantile(values: np.ndarray, quantiles: Iterable[float], weights: np.ndarray) -> np.ndarray:
    values = np.asarray(values, dtype=float)
    weights = normalize_weights(weights)
    quantiles = np.asarray(list(quantiles), dtype=float)
    if values.ndim != 1 or len(values) != len(weights):
        raise ValueError("values and weights must be one-dimensional and equally sized")
    if np.any((quantiles < 0) | (quantiles > 1)):
        raise ValueError("quantiles must be in [0, 1]")
    order = np.argsort(values)
    v = values[order]
    w = weights[order]
    cumulative = np.cumsum(w) - 0.5 * w
    cumulative = np.concatenate(([0.0], cumulative, [1.0]))
    padded_values = np.concatenate(([v[0]], v, [v[-1]]))
    return np.interp(quantiles, cumulative, padded_values)


def summarize_x(x: np.ndarray, weights: np.ndarray | None = None, epsilon: float = 0.005) -> PosteriorSummary:
    x = np.asarray(x, dtype=float)
    if x.ndim != 1 or x.size == 0 or not np.all(np.isfinite(x)):
        raise ValueError("x must be a non-empty finite one-dimensional array")
    if epsilon <= 0:
        raise ValueError("epsilon must be positive")
    if weights is None:
        weights = np.ones_like(x)
    w = normalize_weights(np.asarray(weights, dtype=float))
    if len(w) != len(x):
        raise ValueError("weights and x must have the same length")

    mean_x = float(np.sum(w * x))
    variance_x = float(np.sum(w * (x - mean_x) ** 2))
    q025, median, q975 = weighted_quantile(x, [0.025, 0.5, 0.975], w)
    delta = x - GOLDEN_TARGET
    mean_delta = float(np.sum(w * delta))
    variance_delta = float(np.sum(w * (delta - mean_delta) ** 2))
    ess = float(1.0 / np.sum(w**2))

    return PosteriorSummary(
        n_samples=int(x.size),
        effective_sample_size=ess,
        mean_x=mean_x,
        std_x=float(np.sqrt(max(variance_x, 0.0))),
        median_x=float(median),
        q025_x=float(q025),
        q975_x=float(q975),
        mean_delta=mean_delta,
        std_delta=float(np.sqrt(max(variance_delta, 0.0))),
        posterior_mass_delta_positive=float(np.sum(w[delta > 0])),
        posterior_mass_abs_delta_below_epsilon=float(np.sum(w[np.abs(delta) < epsilon])),
        epsilon=float(epsilon),
    )


def x_from_density_samples(
    omega_m: np.ndarray,
    omega_de: np.ndarray,
    omega_r: np.ndarray | None = None,
    omega_k: np.ndarray | None = None,
    w0: np.ndarray | None = None,
    wa: np.ndarray | None = None,
) -> np.ndarray:
    """Compute X sample-by-sample from background density parameters."""
    arrays = [np.asarray(omega_m, dtype=float), np.asarray(omega_de, dtype=float)]
    n = len(arrays[0])
    if any(a.ndim != 1 or len(a) != n for a in arrays):
        raise ValueError("omega_m and omega_de must be equally sized one-dimensional arrays")

    def optional(value: np.ndarray | None, default: float) -> np.ndarray:
        if value is None:
            return np.full(n, default, dtype=float)
        arr = np.asarray(value, dtype=float)
        if arr.ndim != 1 or len(arr) != n:
            raise ValueError("Optional parameter arrays must match sample length")
        return arr

    omega_r_arr = optional(omega_r, 0.0)
    omega_k_arr = optional(omega_k, 0.0)
    w0_arr = optional(w0, -1.0)
    wa_arr = optional(wa, 0.0)

    output = np.empty(n, dtype=float)
    for i in range(n):
        params = CosmologyParameters(
            omega_m=float(arrays[0][i]),
            omega_de=float(arrays[1][i]),
            omega_r=float(omega_r_arr[i]),
            omega_k=float(omega_k_arr[i]),
            w0=float(w0_arr[i]),
            wa=float(wa_arr[i]),
        )
        output[i] = diagnostic_x(params)
    return output
