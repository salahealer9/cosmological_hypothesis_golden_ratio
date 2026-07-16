# Locked likelihood smoke-test attempt history

## Run 001 — implementation failure

The smoke-test script passed a `pathlib.Path` object to Cobaya 3.5.4's
`yaml_load_file`, which expected a string. No model or likelihood was
initialized.

Correction: convert the YAML path to `str`.

## Run 002 — missing CosmoRec build capability

The installed CAMB package reported version 1.5.0 but had not been compiled
with CosmoRec support. Model initialization stopped when the released chain
configuration requested `recombination_model: CosmoRec`.

Correction: build CosmoRec 2.0.3b with position-independent C++ objects and
build the pinned CAMB 1.5.0 source against it.

## Run 003 — serialized null ACT data version

The released updated YAML serialized the ACT likelihood's generic component
version as null. This overrode the pinned likelihood class default `v1.0`,
causing a path join with `None`.

Correction: normalize the ACT data version to `v1.0` in the runtime copy of
the configuration. The released YAML remained unchanged.

## Run 004 — serialized pre-release ACT filename

The released updated YAML contained the pre-release ACT input filename
`dr6_data_cmb_sacc_oct22.fits`, while the pinned public package uses
`v1.0/dr6_data_cmbonly.fits`.

Correction: normalize the runtime input filename to the pinned public
package filename. The released YAML remained unchanged.

## Run 005 — unadvertised CAMB derived output

CAMB 1.5.0 exposes `taurend`, but Cobaya 3.5.4 did not advertise that field
to its dependency resolver. Model construction therefore could not assign
the derived output requested by the released YAML.

Correction: apply a process-local capability shim that advertises the
existing CAMBdata `taurend` field. Neither CAMB nor Cobaya source files were
modified.

## Run 006 — pass

CAMB 1.5.0 with CosmoRec 2.0.3b initialized successfully. All four locked
likelihood components initialized and returned finite values during exactly
one serial posterior evaluation.

No sampler, MPI process, or MCMC chain was started. No target statistic was
computed, and no numerical parameter, likelihood, posterior, or derived
values were recorded in the provenance output.
