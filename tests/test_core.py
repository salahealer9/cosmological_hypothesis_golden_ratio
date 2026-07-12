from math import sqrt

import pytest

from golden_ratio_cosmology.core import (
    GOLDEN_TARGET,
    PHI,
    CosmologyParameters,
    analytic_flat_lcdm_age,
    diagnostic_x,
    dimensionless_age,
    ideal_flat_lcdm_prediction,
)


def test_golden_geometry_identity() -> None:
    assert 1.0 + 1.0 / PHI**2 == pytest.approx(3.0 - PHI, abs=1e-15)
    assert 3.0 - PHI == pytest.approx((5.0 - sqrt(5.0)) / 2.0, abs=1e-15)


def test_ideal_prediction_values() -> None:
    result = ideal_flat_lcdm_prediction()
    assert result["omega_m"] == pytest.approx(0.3157273701547816, abs=1e-15)
    assert result["omega_lambda"] == pytest.approx(0.6842726298452184, abs=1e-15)
    assert result["omega_m"] + result["omega_lambda"] == pytest.approx(1.0, abs=1e-15)


def test_analytic_and_numerical_age_agree() -> None:
    omega_m = 0.3157273701547816
    params = CosmologyParameters(omega_m=omega_m, omega_de=1.0 - omega_m)
    assert dimensionless_age(params) == pytest.approx(analytic_flat_lcdm_age(omega_m), rel=1e-11)


def test_prediction_satisfies_hypothesis() -> None:
    result = ideal_flat_lcdm_prediction()
    params = CosmologyParameters(
        omega_m=result["omega_m"],
        omega_de=result["omega_lambda"],
    )
    assert diagnostic_x(params) == pytest.approx(GOLDEN_TARGET, abs=2e-13)


def test_closure_is_enforced() -> None:
    with pytest.raises(ValueError, match="do not close"):
        dimensionless_age(CosmologyParameters(omega_m=0.3, omega_de=0.6))
