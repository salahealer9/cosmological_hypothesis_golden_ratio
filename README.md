# Golden-Ratio Cosmological Hypothesis

[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.21322457.svg)](https://doi.org/10.5281/zenodo.21322457)

A reproducible research project for testing the dimensionless hypothesis

\[
\mathcal H_\Phi:\qquad X \equiv H_0 t_0\sqrt{\Omega_{\Lambda,0}}=\Phi^{-1/2},
\qquad \Phi=\frac{1+\sqrt5}{2}.
\]

The project deliberately separates:

1. the **geometric clue** that motivated the hypothesis;
2. the **mathematical consequence** inside an idealized flat matter–\(\Lambda\) model;
3. the **observational test** using posterior samples and likelihoods;
4. the **physical-mechanism question**, which remains open.

This is not presented as established cosmology. The relation was noticed after modern cosmological parameters were already known, so Planck-era agreement is discovery evidence only, not an independent confirmation.

## Preregistration status

The confirmatory protocol and analysis configuration were frozen before the held-out analysis under the immutable release tag:

```text
v0.1.0-preregistration-freeze
```

- **Version DOI:** [10.5281/zenodo.21322457](https://doi.org/10.5281/zenodo.21322457)
- **Concept DOI:** [10.5281/zenodo.21322456](https://doi.org/10.5281/zenodo.21322456)

The version DOI identifies this exact frozen preregistration release. The concept DOI resolves to the project record and should be used when referring to the evolving project across releases. Confirmatory work must proceed outside the frozen tag, on a separate analysis branch.

## Exact idealized prediction

For a spatially flat universe containing pressureless matter and a cosmological constant, with radiation neglected,

\[
H_0t_0=\frac{2}{3\sqrt{\Omega_\Lambda}}
\operatorname{arsinh}\!\sqrt{\frac{\Omega_\Lambda}{\Omega_m}}.
\]

Imposing \(H_0t_0\sqrt{\Omega_\Lambda}=\Phi^{-1/2}\) gives

\[
\frac{\Omega_\Lambda}{\Omega_m}
=\sinh^2\!\left(\frac{3}{2\sqrt\Phi}\right),
\]

and flatness then predicts

\[
\Omega_m=0.3157273701547816,\qquad
\Omega_\Lambda=0.6842726298452184.
\]

These numbers are consequences of the hypothesis in the stated approximation, not fitted values.

## Quick start

```bash
cd cosmological_hypothesis_golden_ratio
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -e '.[dev]'
pytest
python scripts/baseline_report.py
```

To analyse a posterior chain exported as CSV:

```bash
python scripts/analyze_chain.py \
  --input data/raw/chain.csv \
  --omega-m-column omega_m \
  --omega-de-column omega_lambda \
  --weight-column weight \
  --output results/chain_diagnostic.json
```

If a chain supplies \(H_0\) and age directly, pass `--h0-column` and `--age-gyr-column`. Otherwise the script computes the dimensionless age from the cosmological density parameters.

## Research workflow

- Read [`docs/HYPOTHESIS.md`](docs/HYPOTHESIS.md) for the precise claim.
- Treat [`docs/PREREGISTRATION.md`](docs/PREREGISTRATION.md) and [`config/analysis_plan.toml`](config/analysis_plan.toml) at `v0.1.0-preregistration-freeze` as immutable.
- Follow [`docs/DATA_PLAN.md`](docs/DATA_PLAN.md) and preserve raw-file checksums.
- Record every model and dataset combination in the analysis outputs.
- Keep exploratory and confirmatory outputs in separate subdirectories.
- Label all post-freeze deviations from the preregistered protocol explicitly.

## Repository map

```text
cosmological_hypothesis_golden_ratio/
├── config/                 # frozen analysis choices
├── data/raw/               # untouched external chains/data; not committed by default
├── data/derived/           # reproducible transformations
├── docs/                   # hypothesis, preregistration, statistics, provenance
├── notebooks/              # transparent exploratory calculations
├── results/                # generated reports and figures
├── scripts/                # command-line entry points
├── src/                    # tested numerical implementation
└── tests/                  # mathematical and numerical regression tests
```

## Core scientific safeguards

- No fitted time unit such as “\(10\,\mathrm{Gyr}\)”. The primary relation is dimensionless.
- No confirmation claim from the dataset that inspired the hypothesis.
- Full posterior covariance must be preserved; central-value error propagation is not the primary analysis.
- The exact relation is tested against radiation, massive neutrinos, curvature, and non-constant dark energy.
- Prior sensitivity and the look-elsewhere problem are reported explicitly.
- A numerical match is not treated as a physical derivation.

## Initial primary sources

- Planck Collaboration, *Planck 2018 results. VI. Cosmological parameters*, A&A 641, A6 (2020), DOI: 10.1051/0004-6361/201833910.
- DESI Collaboration, *DESI DR2 Results II: Measurements of Baryon Acoustic Oscillations and Cosmological Constraints*, arXiv:2503.14738.
- ACT Collaboration, *The Atacama Cosmology Telescope: DR6 Power Spectra, Likelihoods and ΛCDM Parameters*, arXiv:2503.14452.
- Brout et al., *The Pantheon+ Analysis: Cosmological Constraints*, ApJ 938, 110 (2022), DOI: 10.3847/1538-4357/ac8e04.

See [`references.bib`](references.bib) and [`docs/SOURCE_PROVENANCE.md`](docs/SOURCE_PROVENANCE.md).

## Citation

For the exact frozen preregistration release, cite:

> Gherbi, S.-E. (2026). *Golden-Ratio Cosmological Hypothesis* (Version v0.1.0-preregistration-freeze). Zenodo. https://doi.org/10.5281/zenodo.21322457

Citation metadata is also provided in [`CITATION.cff`](CITATION.cff). Use the concept DOI `10.5281/zenodo.21322456` when citing the project as a whole rather than this specific archived version.

## Author

Salah-Eddin Gherbi, Independent Researcher  
ORCID: 0009-0005-4017-1095
