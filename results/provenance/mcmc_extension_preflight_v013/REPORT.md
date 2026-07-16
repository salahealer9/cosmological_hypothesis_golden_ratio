# MCMC extension preflight v0.1.3

Overall status: **PASS**

All three staged datasets passed the no-sampler four-rank preflight:

- `planck_lcdm_camb`
- `actlite_lcdm_camb`
- `p-actlite_lcdm_camb`

The locked execution layout was four MPI ranks with two OpenMP threads
per rank. Each rank was bound to one physical core and both hardware
threads of that core.

The signed `v0.1.3-mcmc-extension-lock` tag, execution-critical hashes,
runtime compatibility settings, checkpoints, output prefixes, and
original seed checksums passed.

No sampler was initialized, no chain row was appended, and no target
statistic or scientific result was computed.
