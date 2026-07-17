# GCP execution boundary before hardware migration

Overall status: **SEALED**

This boundary was created after completion of the target-blind
`segment-002` MCMC extensions and their convergence diagnostics, and
before any Hetzner provisioning, benchmarking, runtime selection, or
additional sampling.

## Current chain state

- `planck_lcdm_camb`: 22,897 rows per chain
- `actlite_lcdm_camb`: 26,027 rows per chain
- `p-actlite_lcdm_camb`: 26,943 rows per chain

All chains remain append-only continuations of the released ACT DR6.02
chains through the previously sealed segment records.

## Confirmatory convergence status

The original convergence requirements remain unchanged:

- GetDist R-1 <= 0.01
- rank R-hat <= 1.01
- bulk ESS(X) >= 10,000
- tail ESS(X) >= 10,000

The R-1 and rank-R-hat requirements pass for all three datasets. The
bulk/tail ESS requirements have not yet been reached.

This state is recorded as:

**Original confirmatory convergence gate not reached.**

No posterior target location, hypothesis residual, or scientific verdict
was computed as part of this boundary.

## Migration preservation

The boundary contains:

- checksums for every staged chain and control file;
- exact row counts and chain-file hashes;
- copies of all small checkpoint and runtime-control files;
- software and hardware environment records;
- the target-blind convergence diagnostics;
- the checksum and contents list for the transfer archive.

No additional MCMC sampling is permitted on GCP after this boundary
unless a new prospective execution amendment is committed first.
