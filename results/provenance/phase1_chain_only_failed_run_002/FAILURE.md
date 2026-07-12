# Phase 1 chain-only gate failure 002

All three CAMB background transformations passed technical validation.

All three datasets passed:

- GetDist multivariate R-1 <= 0.01
- rank-normalized split R-hat <= 1.01

All three failed the frozen derived-X effective-sample-size gate:

- bulk ESS(X) >= 10,000
- tail ESS(X) >= 10,000

No target-bearing posterior summary, negative-control result, derived NPZ
array, or scientific verdict was written.

Under v0.1.2-chain-ingestion-lock, the required response is to extend or
rerun the exact released MCMC configurations. Burn-in, thinning, chain
removal, and convergence thresholds remain unchanged.
