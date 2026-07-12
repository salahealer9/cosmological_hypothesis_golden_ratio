"""Core mathematical definitions for the golden-ratio cosmology project.

The primary diagnostic is

    X = H0 * t0 * sqrt(Omega_de0),

where H0*t0 is dimensionless.  For a general FLRW background, H0*t0 is
computed as an integral over the scale factor.  The idealized analytic
prediction applies only to flat matter + cosmological-constant cosmology with
radiation neglected.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import asinh, isfinite, sqrt, sinh
from typing import Final

import numpy as np
from scipy.integrate import quad

PHI: Final[float] = (1.0 + sqrt(5.0)) / 2.0
GOLDEN_TARGET: Final[float] = 1.0 / sqrt(PHI)


@dataclass(frozen=True)
class CosmologyParameters:
    """Background parameters at z=0.

    Parameters
    ----------
    omega_m:
        Total non-relativistic matter density fraction.
    omega_de:
        Dark-energy density fraction.
    omega_r:
        Radiation density fraction, including relativistic species if desired.
    omega_k:
        Curvature density fraction.
    w0, wa:
        CPL equation of state w(a) = w0 + wa(1-a).  LambdaCDM is w0=-1, wa=0.

    Notes
    -----
    The parameters should satisfy closure to numerical precision:
    omega_m + omega_de + omega_r + omega_k = 1.
    """

    omega_m: float
    omega_de: float
    omega_r: float = 0.0
    omega_k: float = 0.0
    w0: float = -1.0
    wa: float = 0.0

    def validate(self, closure_tolerance: float = 1e-8) -> None:
        values = (
            self.omega_m,
            self.omega_de,
            self.omega_r,
            self.omega_k,
            self.w0,
            self.wa,
        )
        if not all(isfinite(v) for v in values):
            raise ValueError("All cosmological parameters must be finite.")
        if self.omega_m < 0 or self.omega_de < 0 or self.omega_r < 0:
            raise ValueError("Matter, dark-energy, and radiation densities must be non-negative.")
        closure = self.omega_m + self.omega_de + self.omega_r + self.omega_k
        if abs(closure - 1.0) > closure_tolerance:
            raise ValueError(
                f"Density parameters do not close: sum={closure:.16g}, "
                f"tolerance={closure_tolerance:g}."
            )


def _dark_energy_scaling(a: float, w0: float, wa: float) -> float:
    """Return rho_de(a)/rho_de(1) for the CPL equation of state."""
    return a ** (-3.0 * (1.0 + w0 + wa)) * np.exp(-3.0 * wa * (1.0 - a))


def e2_of_a(a: float, params: CosmologyParameters) -> float:
    """Return E(a)^2 = [H(a)/H0]^2."""
    if not 0.0 < a <= 1.0:
        raise ValueError("Scale factor a must satisfy 0 < a <= 1.")
    params.validate()
    e2 = (
        params.omega_r / a**4
        + params.omega_m / a**3
        + params.omega_k / a**2
        + params.omega_de * _dark_energy_scaling(a, params.w0, params.wa)
    )
    if e2 <= 0.0 or not np.isfinite(e2):
        raise ValueError(f"Unphysical E(a)^2={e2} at a={a}.")
    return float(e2)


def dimensionless_age(params: CosmologyParameters) -> float:
    """Compute H0*t0 = integral_0^1 da / [a E(a)]."""
    params.validate()

    def integrand(a: float) -> float:
        return 1.0 / (a * sqrt(e2_of_a(a, params)))

    value, error = quad(integrand, 0.0, 1.0, epsabs=1e-12, epsrel=1e-12, limit=300)
    if not np.isfinite(value) or error > 1e-8:
        raise RuntimeError(f"Age integral failed: value={value}, estimated error={error}.")
    return float(value)


def analytic_flat_lcdm_age(omega_m: float) -> float:
    """Analytic H0*t0 for flat matter + Lambda with negligible radiation."""
    if not 0.0 < omega_m < 1.0:
        raise ValueError("omega_m must lie strictly between 0 and 1.")
    omega_lambda = 1.0 - omega_m
    return (2.0 / (3.0 * sqrt(omega_lambda))) * asinh(
        sqrt(omega_lambda / omega_m)
    )


def diagnostic_x(params: CosmologyParameters) -> float:
    """Return X = (H0*t0)*sqrt(Omega_de0)."""
    return dimensionless_age(params) * sqrt(params.omega_de)


def golden_residual(params: CosmologyParameters) -> float:
    """Return Delta_Phi = X - Phi^(-1/2)."""
    return diagnostic_x(params) - GOLDEN_TARGET


def ideal_flat_lcdm_prediction() -> dict[str, float]:
    """Return the exact idealized density prediction implied by H_Phi."""
    ratio = sinh(3.0 / (2.0 * sqrt(PHI))) ** 2
    omega_m = 1.0 / (1.0 + ratio)
    omega_lambda = ratio / (1.0 + ratio)
    return {
        "phi": PHI,
        "target_x": GOLDEN_TARGET,
        "omega_lambda_over_omega_m": ratio,
        "omega_m": omega_m,
        "omega_lambda": omega_lambda,
        "h0_t0": analytic_flat_lcdm_age(omega_m),
    }
