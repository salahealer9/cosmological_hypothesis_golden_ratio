# Locked likelihood smoke test

Overall status: **PASS**

Exactly one serial posterior evaluation was requested using the locked Planck+ACT-lite model. The serialized ACT data-version null value and legacy pre-release input filename were normalized in memory to the pinned public package defaults (v1.0/dr6_data_cmbonly.fits). A process-local Cobaya compatibility shim advertised the existing CAMBdata.taurend field requested by the released YAML. Neither source YAML nor installed Cobaya source was modified.

No sampler was created, no MPI or MCMC process was started, no target statistic was computed, and no numerical parameter, likelihood, posterior, or derived values were recorded.

CAMB 1.5.0 was verified as an editable build from the pinned source commit with the CosmoRec class available before model initialization.

## Likelihood components

- `act_dr6_cmbonly.ACTDR6CMBonly`: **PASS** (finite)
- `act_dr6_cmbonly.PlanckActCut`: **PASS** (finite)
- `planck_2018_lowl.EE_sroll2`: **PASS** (finite)
- `planck_2018_lowl.TT`: **PASS** (finite)

## Timing

- Model initialization: `0.8136813600003734` seconds
- Single evaluation: `11.994361418999688` seconds
- Total script: `12.998407475000022` seconds

## Checks

```json
{
  "all_four_likelihoods_finite": true,
  "camb_cosmorec_capability_passed": true,
  "cambdata_taurend_field_present": true,
  "cobaya_source_file_unmodified": true,
  "cobaya_taurend_capability_shim_installed": true,
  "combined_yaml_has_exact_locked_likelihoods": true,
  "finite_logposterior": true,
  "installation_report_passed": true,
  "locked_act_data_file_exists": true,
  "model_initialized": true,
  "no_derived_values_recorded": true,
  "no_mcmc_started": true,
  "no_numerical_likelihood_values_recorded": true,
  "no_parameter_values_recorded": true,
  "no_sampler_created": true,
  "no_target_statistic_computed": true,
  "one_evaluation_completed": true,
  "returned_exact_locked_likelihoods": true,
  "runtime_act_data_version_is_v1_0": true,
  "runtime_act_input_file_is_pinned": true,
  "serialized_act_input_file_is_allowed": true,
  "serialized_act_version_is_null_or_v1_0": true,
  "software_versions_match": true,
  "tracked_worktree_clean_before_run": true
}
```
