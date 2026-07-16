# CAMB 1.5.0 with CosmoRec 2.0.3b

Overall status: **PASS**

The official chain configurations require the `CosmoRec` recombination
class. The original binary CAMB 1.5.0 installation did not expose that
class.

CosmoRec 2.0.3b was therefore built from its archived source after
adding `-fPIC` to the exact C++ compiler assignment. CAMB tag 1.5.0 was
built from its pinned Git commit with both `recfast` and `cosmorec`
enabled and linked against the rebuilt CosmoRec static library.

The resulting CAMB Python installation:

- reports metadata and module version 1.5.0;
- imports from the controlled source checkout;
- successfully instantiates the CosmoRec recombination class;
- has no broken Python requirements;
- has no unresolved shared-library dependencies.

No CMB spectrum, likelihood, sampler, MCMC chain, target statistic, or
scientific result was calculated during this capability verification.
