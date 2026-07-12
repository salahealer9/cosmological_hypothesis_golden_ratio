import numpy as np
import pytest

from golden_ratio_cosmology.core import GOLDEN_TARGET
from golden_ratio_cosmology.posterior import summarize_x, weighted_quantile


def test_weighted_quantile_uniform_weights() -> None:
    x = np.arange(1.0, 6.0)
    w = np.ones_like(x)
    median = weighted_quantile(x, [0.5], w)[0]
    assert median == pytest.approx(3.0)


def test_summary_at_target() -> None:
    x = np.full(100, GOLDEN_TARGET)
    result = summarize_x(x, epsilon=1e-6)
    assert result.mean_delta == pytest.approx(0.0, abs=1e-15)
    assert result.posterior_mass_abs_delta_below_epsilon == pytest.approx(1.0)
