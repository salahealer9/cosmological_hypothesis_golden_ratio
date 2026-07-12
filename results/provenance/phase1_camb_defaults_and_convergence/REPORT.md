# CAMB defaults and chain-convergence audit

Overall status: **PASS**

No posterior central values or golden-ratio residuals were computed.

## Exact software and constants

- CAMB: `1.5.0`
- `default_nnu`: `3.044`
- `COBE_CMBTemp`: `2.7255` K

## Resolved default background

- `omk`: `0.0`
- `omnuh2`: `0.000644866570625114`
- `num_nu_massless`: `2.0293333333333337`
- `num_nu_massive`: `1`
- `nu_mass_eigenstates`: `1`
- dark-energy class: `DarkEnergyFluid`
- `w`: `-1.0`
- `wa`: `0.0`

## Released-chain sampler/progress metadata

### `planck_lcdm_camb`

Sampler:

```json
{
  "mcmc": {
    "Rminus1_cl_level": 0.95,
    "Rminus1_cl_stop": 0.05,
    "Rminus1_single_split": 4,
    "Rminus1_stop": 0.01,
    "blocking": [
      [
        1,
        [
          "ombh2",
          "omch2",
          "cosmomc_theta",
          "tau"
        ]
      ],
      [
        1,
        [
          "logA",
          "ns"
        ]
      ],
      [
        26,
        [
          "A_planck"
        ]
      ]
    ],
    "burn_in": 0,
    "callback_every": null,
    "callback_function": null,
    "check_every": null,
    "covmat": "lcdm.covmat",
    "covmat_params": null,
    "drag": false,
    "drag_limits": null,
    "fallback_covmat_scale": 4,
    "learn_every": "40d",
    "learn_proposal": true,
    "learn_proposal_Rminus1_max": 10.0,
    "learn_proposal_Rminus1_max_early": 30.0,
    "learn_proposal_Rminus1_min": 0.0,
    "max_samples": Infinity,
    "max_tries": "40d",
    "measure_speeds": true,
    "output_every": "60s",
    "oversample": null,
    "oversample_power": 0.4,
    "oversample_thin": true,
    "proposal_scale": 2.4,
    "seed": null,
    "temperature": 1,
    "version": "3.5.4"
  }
}
```

Final progress diagnostics:

```json
{
  "N": 72539.0,
  "Rminus1": 0.004164,
  "Rminus1_cl": 0.046883,
  "acceptance_rate": 0.926749,
  "timestamp": "2025-01-16T13:01:06.320255"
}
```

### `actlite_lcdm_camb`

Sampler:

```json
{
  "mcmc": {
    "Rminus1_cl_level": 0.95,
    "Rminus1_cl_stop": 0.05,
    "Rminus1_single_split": 4,
    "Rminus1_stop": 0.01,
    "blocking": [
      [
        1,
        [
          "ombh2",
          "omch2",
          "cosmomc_theta",
          "tau"
        ]
      ],
      [
        1,
        [
          "logA",
          "ns"
        ]
      ],
      [
        32,
        [
          "A_act",
          "P_act"
        ]
      ]
    ],
    "burn_in": 0,
    "callback_every": null,
    "callback_function": null,
    "check_every": null,
    "covmat": "lcdm.covmat",
    "covmat_params": null,
    "drag": false,
    "drag_limits": null,
    "fallback_covmat_scale": 4,
    "learn_every": "40d",
    "learn_proposal": true,
    "learn_proposal_Rminus1_max": 10.0,
    "learn_proposal_Rminus1_max_early": 30.0,
    "learn_proposal_Rminus1_min": 0.0,
    "max_samples": Infinity,
    "max_tries": "40d",
    "measure_speeds": true,
    "output_every": "60s",
    "oversample": null,
    "oversample_power": 0.4,
    "oversample_thin": true,
    "proposal_scale": 2.4,
    "seed": null,
    "temperature": 1,
    "version": "3.5.4"
  }
}
```

Final progress diagnostics:

```json
{
  "N": 86685.0,
  "Rminus1": 0.011515,
  "Rminus1_cl": NaN,
  "acceptance_rate": 0.952093,
  "timestamp": "2025-01-17T13:46:51.086216"
}
```

### `p-actlite_lcdm_camb`

Sampler:

```json
{
  "mcmc": {
    "Rminus1_cl_level": 0.95,
    "Rminus1_cl_stop": 0.05,
    "Rminus1_single_split": 4,
    "Rminus1_stop": 0.01,
    "blocking": [
      [
        1,
        [
          "ombh2",
          "omch2",
          "cosmomc_theta",
          "tau"
        ]
      ],
      [
        1,
        [
          "logA",
          "ns"
        ]
      ],
      [
        23,
        [
          "A_planck"
        ]
      ],
      [
        32,
        [
          "P_act"
        ]
      ]
    ],
    "burn_in": 0,
    "callback_every": null,
    "callback_function": null,
    "check_every": null,
    "covmat": "lcdm.covmat",
    "covmat_params": null,
    "drag": false,
    "drag_limits": null,
    "fallback_covmat_scale": 4,
    "learn_every": "40d",
    "learn_proposal": true,
    "learn_proposal_Rminus1_max": 10.0,
    "learn_proposal_Rminus1_max_early": 30.0,
    "learn_proposal_Rminus1_min": 0.0,
    "max_samples": Infinity,
    "max_tries": "40d",
    "measure_speeds": true,
    "output_every": "60s",
    "oversample": null,
    "oversample_power": 0.4,
    "oversample_thin": true,
    "proposal_scale": 2.4,
    "seed": null,
    "temperature": 1,
    "version": "3.5.4"
  }
}
```

Final progress diagnostics:

```json
{
  "N": 89936.0,
  "Rminus1": 0.00748,
  "Rminus1_cl": 0.076828,
  "acceptance_rate": 0.987333,
  "timestamp": "2025-01-17T13:50:01.248266"
}
```

## Checks

```json
{
  "all_three_chain_sampler_blocks_present": true,
  "all_three_progress_blocks_present": true,
  "camb_version_is_1_5_0": true,
  "flat_default": true,
  "lambda_default_w": true,
  "lambda_default_wa": true,
  "no_golden_ratio_statistic_computed": true,
  "one_massive_neutrino_default": true,
  "positive_massive_neutrino_density": true
}
```
