#!/usr/bin/env python3
"""Print the exact idealized prediction and numerical cross-checks."""

from __future__ import annotations

import json

from golden_ratio_cosmology.core import (
    CosmologyParameters,
    diagnostic_x,
    ideal_flat_lcdm_prediction,
)


def main() -> None:
    result = ideal_flat_lcdm_prediction()
    params = CosmologyParameters(
        omega_m=result["omega_m"],
        omega_de=result["omega_lambda"],
    )
    result["numerical_x"] = diagnostic_x(params)
    result["absolute_residual"] = abs(result["numerical_x"] - result["target_x"])
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
