# Four-rank MCMC threading benchmark

Overall status: **PASS**

The benchmark performed finite, target-blind posterior evaluations at existing chain points. No sampler or MCMC chain was started.

## Fixed selection rule

Choose two OpenMP threads per rank only when the geometric-mean throughput speedup is at least 1.05 and no individual dataset is slower than 0.95 times the one-thread result.

## Results

- `planck_lcdm_camb`: two/one throughput ratio `1.211619`
- `actlite_lcdm_camb`: two/one throughput ratio `1.152592`
- `p-actlite_lcdm_camb`: two/one throughput ratio `1.097473`

Geometric-mean speedup: `1.152954`

Selected OpenMP threads per MPI rank: **2**

Reason: two threads met both the aggregate and per-dataset speed rules.

No target statistic, hypothesis residual, posterior summary, or scientific verdict was computed.
