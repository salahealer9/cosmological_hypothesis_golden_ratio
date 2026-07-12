# Statistical protocol

## 1. Why central-value matching is insufficient

The quantities \(H_0\), \(t_0\), and \(\Omega_\Lambda\) are correlated derived parameters. Multiplying published means and propagating independent standard errors generally gives the wrong uncertainty. The primary calculation must evaluate \(X\) sample-by-sample from a joint posterior chain or within the likelihood sampler.

## 2. Posterior diagnostic

For each posterior sample \(\theta_i\), compute

\[
X_i=H_0(\theta_i)t_0(\theta_i)\sqrt{\Omega_{\Lambda,0}(\theta_i)},
\qquad
\Delta_{\Phi,i}=X_i-\Phi^{-1/2}.
\]

Report weighted median, 68% and 95% credible intervals, posterior sign probability, effective sample size, and the full machine-readable sample-derived summary.

The arbitrary interval event \(|\Delta_\Phi|<\epsilon\) is descriptive only and must use the preregistered \(\epsilon\).

## 3. Model comparison

An exact equality is a point model. Compare it with ordinary \(\Lambda\)CDM through one or more of:

- nested sampling with the exact constraint implemented directly;
- thermodynamic integration;
- a validated Savage–Dickey ratio after reparameterizing the model by \(\delta_\Phi\).

The Bayes factor is reported as a function of the declared prior scale. No prior is chosen after seeing which one helps the hypothesis.

## 4. Predictive validation

The strongest available test is out-of-sample prediction. Fit M0 and MΦ to the training likelihood declared in advance, then compare predictive log scores on a held-out likelihood block. Plausible splits include CMB-trained versus BAO/SN-held-out, subject to correct treatment of shared calibration and nuisance information.

## 5. Dataset tension

A combined posterior can appear artificially precise when datasets are in tension. Report per-dataset diagnostics before the combined result and use a declared tension statistic or suspiciousness measure where feasible.

## 6. Look-elsewhere analysis

Define a finite grammar of simple constants before simulation, for example:

\[
\mathcal C=\{\Phi^p,\;1\pm\Phi^{-p},\;\sqrt{1\pm\Phi^{-p}}:\;p=1,2,3,4\},
\]

with inadmissible real expressions removed. Evaluate the minimum standardized distance between each null-simulated posterior centre and any member of \(\mathcal C\). This quantifies the cost of having searched multiple nearby expressions.

The grammar above is only a placeholder. It must be replaced by an honest record of the actual exploratory search.

## 7. Reproducibility outputs

Each run must save:

- software and environment versions;
- input checksums;
- exact command line and configuration;
- random seeds;
- posterior diagnostics;
- tables and figures from machine-readable intermediates;
- a limitations block generated from the frozen configuration.
