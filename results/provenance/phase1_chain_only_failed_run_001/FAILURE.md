# Phase 1 chain-only failed execution 001

The first target-bearing execution stopped during the Planck derived-X
GetDist convergence calculation.

Cause:

`MCSamples` was constructed with separate samples and weights but without
loglikes. `getGelmanRubin()` called `getSeparateChains()`, which attempted
to slice `self.loglikes`; because it was `None`, execution raised:

    TypeError: 'NoneType' object is not subscriptable

No posterior summary, negative-control result, scientific verdict, or
derived NPZ product was written. The corrected implementation preserves
the released `minuslogpost` arrays and supplies them to GetDist.
