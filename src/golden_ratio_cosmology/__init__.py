"""Golden-ratio cosmology: exact relations and reproducible diagnostics."""

from .core import (
    PHI,
    GOLDEN_TARGET,
    CosmologyParameters,
    dimensionless_age,
    diagnostic_x,
    ideal_flat_lcdm_prediction,
)

__all__ = [
    "PHI",
    "GOLDEN_TARGET",
    "CosmologyParameters",
    "dimensionless_age",
    "diagnostic_x",
    "ideal_flat_lcdm_prediction",
]
