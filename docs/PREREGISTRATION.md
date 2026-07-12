# Preregistration

**Status:** DRAFT — the analysis must not be described as confirmatory until this document, the matching configuration, and the data manifest have been frozen, versioned, and timestamped.

## 0. Freeze checklist

- [x] The hypothesis statement and all primary decision rules are final.
- [x] This document is frozen and versioned.
- [x] Freeze date and time (UTC): Jul 12 12:13:45 PM UTC 2026
- [x] Git commit hash: ____________________  # Will fill after commit
- [x] Signed Git tag: v0.1.0-preregistration-freeze
- [x] `config/analysis_plan.toml` is frozen and agrees exactly with this document.
- [x] Exact likelihood releases, dataset combinations, nuisance treatments, and exclusions are recorded in `config/analysis_plan.toml`.
- [x] Raw-data SHA-256 checksums are recorded in `data/raw/checksums.txt`.
- [x] Derived-data SHA-256 checksums are recorded in `data/derived/checksums.txt` when derived products first exist.
- [x] The software environment and dependency lock file are recorded.
- [x] Test command: `PYTHONPATH=src pytest -q`.
- [x] Freeze test result: 7 passed, 0 failed.
- [x] The honest pre-freeze search record has replaced the placeholder constant grammar.
- [x] No confirmatory ACT DR6 or DESI DR2 value of \(\Delta_\Phi\), Bayes factor, predictive score, or constrained-model fit has been inspected before completing this checklist.

## 1. Research question

Does an independently inferred cosmological posterior support the exact dimensionless constraint

\[
\mathcal H_\Phi:\qquad
H_0t_0\sqrt{\Omega_{\Lambda,0}}=\Phi^{-1/2},
\]

within spatially flat \(\Lambda\)CDM, and does imposing this constraint improve or degrade genuinely held-out predictive performance relative to ordinary flat \(\Lambda\)CDM?

The exact target is

\[
\Phi^{-1/2}=0.7861513777574233\ldots .
\]

## 2. Discovery and validation separation

### 2.1 Discovery context

The following are discovery inputs and cannot be used to claim independent confirmation:

- the golden-ratio geometry that generated the numerical clue;
- the Planck 2018 parameter region and the previously known age of the Universe;
- any exploratory calculation performed before this preregistration was frozen.

Planck 2018 may be used as a conditioning dataset in a sequential predictive calculation and for pipeline verification, but it remains part of the discovery history.

### 2.2 Confirmatory data families

Before downloading or inspecting confirmatory posterior residuals, the exact release, likelihood version, chain or likelihood identifiers, checksums, nuisance treatment, external priors, and inclusion/exclusion rules must be written into `config/analysis_plan.toml`.

The intended confirmatory families are:

1. **Primary validation:** the ACT DR6.02 CMB-only likelihood or an exactly specified ACT DR6.02 likelihood block that does not include Planck high-\(\ell\) information. Any low-\(\ell\), optical-depth, calibration, or other external information required to identify the cosmology must be frozen and classified explicitly as conditioning information.
2. **Secondary validation:** the DESI DR2 BAO likelihood, using the preregistered redshift-bin combination. A released joint chain containing Planck, ACT, supernova, or other external likelihoods is not by itself an independent DESI validation; the DESI BAO likelihood contribution must be evaluated separately or the likelihood factorization must be demonstrably recoverable.
3. **Robustness data:** one preselected supernova compilation, plus any alternative supernova compilations declared before inspection and analysed separately.

No dataset may be counted as independent if its likelihood, sky information, calibration, covariance, nuisance prior, compressed CMB prior, or posterior product overlaps materially with another component. All overlap must be documented.

## 3. Primary model comparison

- **M0:** standard spatially flat six-parameter \(\Lambda\)CDM.
- **M\(\Phi\):** the same model with the exact derived constraint \(\delta_\Phi=0\), reducing the continuous parameter-space dimension by one.

Define

\[
\delta_\Phi
=
H_0t_0\sqrt{\Omega_{\Lambda,0}}-\Phi^{-1/2}.
\]

M\(\Phi\) is the nested point \(\delta_\Phi=0\). The implementation must impose the constraint inside the sampler or likelihood calculation; replacing it by a narrow numerical tolerance is permitted only after convergence to the exact-constraint result has been demonstrated.

### 3.1 Primary prior convention

The primary M0 evidence calculation will use the standard base-parameter prior family frozen for the selected likelihood implementation. The prior on \(\delta_\Phi\) is then the induced prior obtained from those base-parameter priors. The shared parameters of M0 and M\(\Phi\) must use identical priors.

This induced-prior comparison is primary because a prior written directly in \(\delta_\Phi\) can unintentionally privilege the target through its parameterization.

### 3.2 Preregistered prior-scale sensitivity

For transparency, the Bayes factor will also be reported under the following target-centred Gaussian sensitivity priors:

\[
\delta_\Phi\sim\mathcal N(0,\sigma_\delta^2),
\]

with

1. **Narrow:** \(\sigma_\delta=0.01\);
2. **Medium:** \(\sigma_\delta=0.05\);
3. **Wide:** \(\sigma_\delta=0.10\).

These three widths are frozen before confirmatory inspection. Because they are centred on the proposed relation, they are sensitivity analyses rather than a replacement for the primary induced-prior calculation. No prior width may be selected after seeing which one favours the hypothesis.

## 4. Primary outcomes

The following outcomes will be reported for every primary dataset block and for the preregistered combinations:

1. The posterior distribution of \(\delta_\Phi\) under M0, including weighted median, mean, 68% and 95% credible intervals, posterior sign probability, and effective sample size.
2. The marginal-likelihood ratio or Bayes factor
   \[
   K_{\Phi 0}=\frac{Z_{\mathrm{M\Phi}}}{Z_{\mathrm{M0}}},
   \]
   under the primary prior convention and all three sensitivity widths.
3. The held-out predictive log-score difference
   \[
   \Delta\log p_{\mathrm{pred}}
   =
   \log p(D_{\mathrm{hold}}\mid D_{\mathrm{cond}},\mathrm{M\Phi})
   -
   \log p(D_{\mathrm{hold}}\mid D_{\mathrm{cond}},\mathrm{M0}).
   \]
4. The best-fit likelihood degradation
   \[
   \Delta\chi^2
   =
   \chi^2_{\mathrm{M\Phi}}-\chi^2_{\mathrm{M0}}.
   \]
5. Per-dataset likelihood contributions, not only the combined total.

A posterior interval containing zero is not, by itself, evidence for an exact equality.

## 5. Held-out predictive protocol

The language of conditioning and held-out prediction is used rather than treating cosmological datasets as ordinary machine-learning training and test samples.

### 5.1 Primary sequential prediction

- **Conditioning information:** Planck 2018, using the exact likelihood combination frozen in the configuration and labelled explicitly as discovery-conditioning data.
- **Held-out primary validation:** ACT DR6.02, using the exact non-Planck likelihood block frozen in the configuration.

For each model, compute the posterior predictive density of the ACT block after conditioning on Planck. Any shared calibration, common sky modes, or imported Planck prior must be accounted for; if the required independence or factorization cannot be established, this score will be labelled partially held out rather than independent.

### 5.2 Secondary sequential prediction

- **Conditioning information:** the preregistered CMB block.
- **Held-out secondary validation:** DESI DR2 BAO only, using the preregistered BAO bins and covariance.

The DESI contribution must be evaluated from the DESI BAO likelihood itself or from a validated factorization of a joint likelihood. A joint CMB+DESI posterior chain cannot be treated as a held-out DESI test without recovering the separate likelihood contribution.

### 5.3 Predictive-score computation

The predictive score must integrate over posterior uncertainty rather than insert only a best-fit parameter vector. The numerical estimator, number of posterior draws, stabilization method, and Monte Carlo standard error must be frozen. A reported sign is considered numerically resolved only when repeated posterior batches agree and the estimated numerical uncertainty does not cross zero.

## 6. Operational decision language

The following labels are descriptive rules fixed before confirmatory inspection. They do not replace the complete numerical results.

- **Supported:** the primary induced-prior Bayes factor satisfies \(K_{\Phi0}\ge 3\); none of the three preregistered sensitivity priors gives \(K_{\Phi0}<1\); the primary held-out predictive score is positive beyond its numerical uncertainty; the secondary held-out score is not materially negative; and no material dataset tension is present.
- **Compatible but unsupported:** \(\delta_\Phi=0\) lies in the relevant posterior region, but \(1/3<K_{\Phi0}<3\), the held-out score is unresolved, or prior sensitivity prevents a stable preference.
- **Disfavoured:** the primary comparison gives \(K_{\Phi0}\le 1/3\), or the exact constraint produces \(\Delta\chi^2\ge 9\), or a held-out predictive penalty is negative beyond numerical uncertainty and robust to the declared likelihood alternatives.
- **Inconclusive:** numerical convergence, likelihood overlap, prior dependence, unavailable factorization, or unresolved dataset tension prevents a stable conclusion.

For reporting, \(K_{\Phi0}\ge10\) may be described as strong Bayes-factor support and \(K_{\Phi0}\le0.1\) as strong evidence against, but no single threshold or sigma value will be used as the sole decision rule.

## 7. Dataset-tension criterion

“Material dataset tension” will not be defined using the number of data points, because the likelihood-ratio penalty for one nested exact constraint is not proportional to that number.

For approximately Gaussian, effectively independent posterior constraints on \(\delta_\Phi\), the pairwise tension statistic is

\[
T_{ij}
=
\frac{|\mu_i-\mu_j|}
{\sqrt{\sigma_i^2+\sigma_j^2}}.
\]

Material tension is declared if either:

1. a preregistered independent dataset pair has \(T_{ij}\ge3\); or
2. a calibrated posterior-predictive consistency test gives a two-sided \(p\)-value \(\le0.01\).

Where posterior non-Gaussianity or shared information invalidates \(T_{ij}\), a preregistered suspiciousness or parameter-difference statistic will be used instead. The exact statistic and implementation must be frozen before examining the golden-ratio residuals.

Per-dataset \(\Delta\chi^2\) values will also be reported. They diagnose model misfit but are not, by themselves, a definition of tension between datasets.

## 8. Required robustness checks

Run the exact frozen pipeline under:

- nonzero radiation density;
- the baseline and preregistered alternatives for summed neutrino mass;
- curvature \(\Omega_k\);
- constant-\(w\) dark energy;
- CPL \(w_0w_a\);
- alternative public CMB likelihood choices declared before inspection;
- each preregistered supernova compilation separately, never selected by closeness to the target;
- alternative numerical age integrators and accuracy settings;
- the full-likelihood and foreground-marginalized ACT implementations where computationally feasible.

Robustness analyses may show whether the equality is stable, but they cannot replace the primary flat-\(\Lambda\)CDM result.

## 9. Multiplicity and look-elsewhere audit

Record all constants, transformations, and cosmological products considered before freezing the hypothesis, including powers of \(\Phi\), simple affine combinations, roots, and alternative dimensionless cosmological quantities. The headline result must state explicitly that the exact target was selected after exploratory inspection of known cosmological values.

A finite search grammar must be frozen before the null simulation. The simulation-based audit will estimate how often a comparably simple constant from that declared grammar falls at least as close to a null-simulated cosmological posterior centre as the selected target does.

The look-elsewhere-corrected result is part of the primary interpretation, not an optional appendix.

## 10. Numerical acceptance criteria

- Independent analytic and quadrature calculations must agree to relative error below \(10^{-10}\) for the ideal flat matter–\(\Lambda\) case.
- Confirmatory chains must satisfy \(\widehat R<1.01\) for all sampled and monitored derived parameters.
- Bulk and tail effective sample sizes must each be at least 10,000 for \(\delta_\Phi\), unless the frozen configuration specifies a stricter threshold.
- Independent chains, repeated evidence calculations, or repeated nested-sampling runs must agree within the preregistered numerical tolerance.
- Raw files are immutable and checksum-recorded.
- Burn-in, filtering, weighting, and any storage-only thinning must be specified before examining \(\delta_\Phi\). Thinning must not be used as a substitute for convergence.
- Posterior calculations must preserve sample weights and parameter covariance.
- All failures, warnings, and deviations from the frozen plan must be retained in the run log.

## 11. Data freeze

Before any confirmatory analysis begins:

1. All raw likelihood files, chains, covariance matrices, masks, and metadata must be downloaded into `data/raw/` or referenced through an immutable external archive.
2. SHA-256 checksums must be recorded in `data/raw/checksums.txt`.
3. No raw file may be modified after freezing. A corrected upstream release must be added as a new version, never silently substituted.
4. Derived products must be reproducibly generated from the frozen raw files. Their SHA-256 checksums must be written to `data/derived/checksums.txt`.
5. The configuration, environment, exact commands, random seeds, and software revisions must be committed with the data manifests.
6. The frozen state must be recorded by a signed Git tag and an external timestamp or archival deposit.

Large licensed or impractical raw files need not be committed to Git, but their official source, release identifier, retrieval date, size, and checksum must be recorded.

## 12. Negative controls

The same pipeline will be run, without retuning, against the following preregistered control equalities:

1. \[
   H_0t_0\sqrt{\Omega_{\Lambda,0}}=\Phi^{-1}=0.6180339887\ldots
   \]
2. \[
   H_0t_0\sqrt{\Omega_{\Lambda,0}}=\Phi^{-3/2}=0.4858682718\ldots
   \]
3. \[
   H_0t_0\sqrt{\Omega_{\Lambda,0}}=0.8.
   \]

These controls test whether the implementation mechanically favours exact point constraints or golden-ratio expressions. The first two are far from the discovery region and therefore provide only coarse pipeline controls; they do not replace the search-grammar look-elsewhere audit. Similar support for the controls and \(\mathcal H_\Phi\) would count against specificity.

## 13. Stopping rule and deviations

The confirmatory analysis ends after all frozen primary combinations, prior-width calculations, negative controls, and required robustness checks are completed. Additional datasets, constants, model extensions, prior widths, or likelihood combinations are labelled exploratory and cannot replace the primary result.

Any deviation from this document must be recorded before the affected result is inspected, with:

- the reason for the deviation;
- the time and commit at which it was made;
- whether the change was forced by software/data availability or chosen analytically;
- separate reporting of the original frozen analysis whenever it remains technically possible.
