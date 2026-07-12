# Data acquisition and integrity plan

## 1. Raw data policy

External chains and likelihood products are stored under `data/raw/` and are never edited in place. Each download receives:

- source URL or persistent identifier;
- retrieval date;
- upstream version/release name;
- SHA-256 checksum;
- licence or usage note;
- description of included likelihoods.

The large raw files are ignored by Git. Their provenance manifests and checksums are committed.

## 2. Initial sources

### Planck 2018

Use official Planck Legacy Archive/NASA LAMBDA products or the likelihood and chain links documented by the Planck collaboration. Treat these as discovery/pipeline-validation data unless a specific product was genuinely not inspected during hypothesis formation.

### ACT DR6

Use the public DR6 likelihood/posterior products associated with the primary power-spectrum and ΛCDM-parameter paper. Record all external low-\(\ell\), lensing, or Planck components included in each combination.

### DESI DR2

Use the collaboration's public cosmology chains and posterior-maximization products. The chain name must be decoded into its exact BAO, CMB, and supernova components before it enters an independence claim.

### Supernovae

Choose the primary supernova compilation before evaluating the golden residual. Alternative compilations belong in predefined robustness checks.

## 3. Manifest format

Create one JSON record per external asset:

```json
{
  "dataset": "example",
  "release": "example-v1",
  "filename": "chain.txt",
  "source": "persistent source URL",
  "retrieved_utc": "YYYY-MM-DDTHH:MM:SSZ",
  "sha256": "...",
  "likelihood_components": ["..."],
  "notes": "..."
}
```

## 4. Derived data

Every file under `data/derived/` must be reproducible from raw inputs by a committed script and configuration. Manual spreadsheet edits are prohibited for primary results.
