# MCMC segment-002 production plan

Status: **Frozen before execution**

The first production extensions will be executed sequentially under the
signed v0.1.3 MCMC-extension lock:

- Planck: 4,500 appended rows per chain
- ACT-lite: 4,000 appended rows per chain
- Planck+ACT-lite: 4,000 appended rows per chain

The sizes were selected from target-blind pilot throughput measurements
with an intended wall time of approximately six hours per dataset.

All four chains within each dataset are equal in length before this
segment. The expected final row counts are therefore 22,897, 26,027,
and 26,943 respectively.

No target statistic or scientific result was used to choose these
segment sizes. The target-blind X convergence gate will be run only
after all three extensions pass their append-only integrity checks.
