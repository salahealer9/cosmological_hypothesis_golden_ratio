# Synthetic execution-lock benchmark

Overall status: **PASS**

## Software

```text
Python: 3.11.2
Cobaya: 3.6.2
anesthetic: 2.14.9
mpi4py: 4.1.2
PolyChordLite commit: 370f6af5d59a4d3af2ed3333acfba152fdb7a4cf
```

## Evidence versus analytic result

| Case | Seed | numerical log Z | reported error | analytic log Z | absolute error | Status |
|---|---:|---:|---:|---:|---:|---|
| A | 20260712 | -2.961036 | 0.056849 | -2.995732 | 0.034697 | PASS |
| A | 20260713 | -2.969005 | 0.057294 | -2.995732 | 0.026728 | PASS |
| B_concordant | 20260712 | -2.961036 | 0.056849 | -2.995732 | 0.034697 | PASS |
| B_concordant | 20260713 | -2.969005 | 0.057294 | -2.995732 | 0.026728 | PASS |
| AB_concordant | 20260712 | -4.231759 | 0.062959 | -4.261244 | 0.029485 | PASS |
| AB_concordant | 20260713 | -4.231829 | 0.063077 | -4.261244 | 0.029416 | PASS |
| B_shifted | 20260712 | -2.909508 | 0.056108 | -2.995732 | 0.086224 | PASS |
| B_shifted | 20260713 | -3.002213 | 0.057861 | -2.995732 | 0.006481 | PASS |
| AB_shifted | 20260712 | -8.083060 | 0.060629 | -8.261244 | 0.178184 | PASS |
| AB_shifted | 20260713 | -8.210657 | 0.062568 | -8.261244 | 0.050587 | PASS |

## Independent-seed agreement

| Case | absolute difference | frozen tolerance | Status |
|---|---:|---:|---|
| A | 0.007969 | 0.200000 | PASS |
| AB_concordant | 0.000069 | 0.200000 | PASS |
| AB_shifted | 0.127597 | 0.200000 | PASS |
| B_concordant | 0.007969 | 0.200000 | PASS |
| B_shifted | 0.092705 | 0.200000 | PASS |

## Suspiciousness benchmark

| Pair | median log S | median p | median sigma |
|---|---:|---:|---:|
| Concordant | 0.520286 | 1.000000 | 0.000000 |
| Shifted | -3.487992 | 0.004927 | 2.811743 |

Analytic broad-prior expectations:

- Concordant: log S = 0.500000,
  p = 1, sigma = 0.
- Shifted: log S = -3.500000,
  p = 0.004678,
  sigma = 2.828427.

## Acceptance checks

```json
{
  "AB_concordant_seed20260712": true,
  "AB_concordant_seed20260713": true,
  "AB_concordant_seed_agreement": true,
  "AB_shifted_seed20260712": true,
  "AB_shifted_seed20260713": true,
  "AB_shifted_seed_agreement": true,
  "A_seed20260712": true,
  "A_seed20260713": true,
  "A_seed_agreement": true,
  "B_concordant_seed20260712": true,
  "B_concordant_seed20260713": true,
  "B_concordant_seed_agreement": true,
  "B_shifted_seed20260712": true,
  "B_shifted_seed20260713": true,
  "B_shifted_seed_agreement": true,
  "tension_concordant_logS_within_0_5_of_expectation": true,
  "tension_concordant_sigma_below_1": true,
  "tension_shifted_exceeds_concordant_by_1_5_sigma": true,
  "tension_shifted_logS_within_0_5_of_expectation": true,
  "tension_shifted_p_below_0_03": true,
  "tension_shifted_sigma_above_2_2": true
}
```
