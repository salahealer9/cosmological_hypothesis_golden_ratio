# ACT DR6.02 chain-structure audit

Overall status: **PASS**

This audit did not calculate cosmological posterior summaries, `delta_Phi`, Bayes factors, or a scientific verdict.

## `planck_lcdm_camb`

- Chain files: `4`
- Stored rows: `72539`
- Weight ESS before any external row exclusion: `67499.0`
- Declared likelihoods: `act_dr6_cmbonly.PlanckActCut, planck_2018_lowl.EE_sroll2, planck_2018_lowl.TT`
- Declared theory: `camb`
- H0-name candidates: `['H0']`
- Age-name candidates: `[]`
- Omega-Lambda-name candidates: `[]`
- Omega-m-name candidates: `[]`
- Official external burn-in entry: `None` (blank/not numerically specified in the ACT table)
- Status: **PASS**

Checks:

```json
{
  "all_rows_finite": true,
  "all_weights_positive": true,
  "chain_files_found": true,
  "headers_match_across_chains": true,
  "input_yaml_found": true,
  "likelihood_block_matches_expected": true,
  "mcmc_sampler_declared": true,
  "minuslogpost_column_second": true,
  "progress_file_found": true,
  "theory_block_matches_expected": true,
  "updated_yaml_found": true,
  "weight_column_first": true
}
```

## `actlite_lcdm_camb`

- Chain files: `4`
- Stored rows: `87427`
- Weight ESS before any external row exclusion: `83272.6`
- Declared likelihoods: `act_dr6_cmbonly.ACTDR6CMBonly, planck_2018_lowl.EE_sroll2`
- Declared theory: `camb`
- H0-name candidates: `['H0']`
- Age-name candidates: `[]`
- Omega-Lambda-name candidates: `[]`
- Omega-m-name candidates: `[]`
- Official external burn-in entry: `None` (blank/not numerically specified in the ACT table)
- Status: **PASS**

Checks:

```json
{
  "all_rows_finite": true,
  "all_weights_positive": true,
  "chain_files_found": true,
  "headers_match_across_chains": true,
  "input_yaml_found": true,
  "likelihood_block_matches_expected": true,
  "mcmc_sampler_declared": true,
  "minuslogpost_column_second": true,
  "progress_file_found": true,
  "theory_block_matches_expected": true,
  "updated_yaml_found": true,
  "weight_column_first": true
}
```

## `p-actlite_lcdm_camb`

- Chain files: `4`
- Stored rows: `90592`
- Weight ESS before any external row exclusion: `89447.7`
- Declared likelihoods: `act_dr6_cmbonly.ACTDR6CMBonly, act_dr6_cmbonly.PlanckActCut, planck_2018_lowl.EE_sroll2, planck_2018_lowl.TT`
- Declared theory: `camb`
- H0-name candidates: `['H0']`
- Age-name candidates: `[]`
- Omega-Lambda-name candidates: `[]`
- Omega-m-name candidates: `[]`
- Official external burn-in entry: `None` (blank/not numerically specified in the ACT table)
- Status: **PASS**

Checks:

```json
{
  "all_rows_finite": true,
  "all_weights_positive": true,
  "chain_files_found": true,
  "headers_match_across_chains": true,
  "input_yaml_found": true,
  "likelihood_block_matches_expected": true,
  "mcmc_sampler_declared": true,
  "minuslogpost_column_second": true,
  "progress_file_found": true,
  "theory_block_matches_expected": true,
  "updated_yaml_found": true,
  "weight_column_first": true
}
```

## Overall checks

```json
{
  "all_chain_audits_pass": true,
  "all_three_expected_chains_audited": true,
  "no_audit_errors": true,
  "no_golden_ratio_statistic_computed": true
}
```
