# MCMC threading benchmark attempt history

## Run 001 — MPI topology configuration failure

The Planck 4x1 configuration passed, but the 4x2 launch used
`--map-by slot:PE=2 --bind-to core`. On this four-core/eight-thread machine,
that requested two physical cores per MPI rank and was rejected by Open MPI
before the Python benchmark began.

No sampler or MCMC chain was started.

Correction: bind one MPI rank to each physical core with
`--map-by core --bind-to core`, expose both hardware threads of that core,
and use `OMP_PLACES=threads`.

## Run 002 — pass

All six finite target-blind configurations passed:

- Planck with one and two OpenMP threads per rank;
- ACT-lite with one and two OpenMP threads per rank;
- Planck+ACT-lite with one and two OpenMP threads per rank.

The predeclared selection rule chose two OpenMP threads per MPI rank.

No sampler, chain extension, target statistic, posterior target summary,
or scientific verdict was produced.
