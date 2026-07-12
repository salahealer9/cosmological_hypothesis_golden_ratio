#!/usr/bin/env python3
"""
Phase 1B chain-structure and ingestion audit for ACT DR6.02 LCDM chains.

This script intentionally does NOT compute posterior means, cosmological
constraints, the golden-ratio target, delta_Phi, Bayes factors, or verdicts.

It audits:
  - exact chain roots and accompanying Cobaya metadata;
  - sample-file column names, dimensions, row counts, weights and finiteness;
  - declared likelihoods, theory code and sampler metadata;
  - availability of parameters needed by a later derived-quantity pipeline;
  - progress-file structure and final convergence diagnostics, if present.

Run from the repository root:

    python scripts/audit_act_chain_structure.py
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import yaml


EXPECTED: dict[str, dict[str, Any]] = {
    "planck_lcdm_camb": {
        "likelihoods": {
            "planck_2018_lowl.TT",
            "planck_2018_lowl.EE_sroll2",
            "act_dr6_cmbonly.PlanckActCut",
        },
        "theory": {"camb"},
        # The official ACT table leaves the burn-in cell blank for this chain.
        "official_external_burnin_fraction": None,
    },
    "actlite_lcdm_camb": {
        "likelihoods": {
            "planck_2018_lowl.EE_sroll2",
            "act_dr6_cmbonly.ACTDR6CMBonly",
        },
        "theory": {"camb"},
        "official_external_burnin_fraction": None,
    },
    "p-actlite_lcdm_camb": {
        "likelihoods": {
            "planck_2018_lowl.TT",
            "planck_2018_lowl.EE_sroll2",
            "act_dr6_cmbonly.PlanckActCut",
            "act_dr6_cmbonly.ACTDR6CMBonly",
        },
        "theory": {"camb"},
        "official_external_burnin_fraction": None,
    },
}

H0_NAMES = {
    "H0", "h0", "H_0", "hubble", "Hubble",
}
AGE_NAMES = {
    "age", "Age", "age_gyr", "AgeGyr", "t0", "t_0",
}
OMEGA_LAMBDA_NAMES = {
    "omegal", "Omega_Lambda", "OmegaLambda", "omega_lambda",
    "Omega_Lambda_0", "Omega_de", "Omega_DE", "omegade",
}
OMEGA_M_NAMES = {
    "omegam", "Omega_m", "OmegaM", "omega_m", "Omega_m_0",
}

CHAIN_RE = re.compile(r"^(?P<root>.+)\.(?P<number>\d+)\.txt$")


@dataclass
class ChainFileAudit:
    path: str
    chain_number: int
    rows: int
    columns: int
    header_columns: list[str]
    first_row_columns: int
    all_rows_finite: bool
    positive_weights: bool
    total_weight: float
    weight_ess: float


def find_one(base: Path, pattern: str) -> Path:
    matches = sorted(base.rglob(pattern))
    if len(matches) != 1:
        raise RuntimeError(
            f"Expected exactly one {pattern!r} beneath {base}; found "
            f"{len(matches)}: {[str(p) for p in matches]}"
        )
    return matches[0]


def root_from_updated_yaml(path: Path) -> Path:
    suffix = ".updated.yaml"
    text = str(path)
    if not text.endswith(suffix):
        raise ValueError(path)
    return Path(text[: -len(suffix)])


def read_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    if not isinstance(data, dict):
        raise RuntimeError(f"{path} did not contain a YAML mapping")
    return data


def classify_params(params: Any) -> dict[str, list[str]]:
    result = {"sampled": [], "derived": [], "fixed": [], "unknown": []}
    if not isinstance(params, dict):
        return result

    for name, spec in params.items():
        if spec is None:
            result["unknown"].append(str(name))
        elif isinstance(spec, (int, float, str, bool)):
            result["fixed"].append(str(name))
        elif isinstance(spec, dict):
            if "prior" in spec:
                result["sampled"].append(str(name))
            elif spec.get("derived") is True or "value" in spec:
                result["derived"].append(str(name))
            elif "ref" in spec or "proposal" in spec:
                result["sampled"].append(str(name))
            else:
                result["unknown"].append(str(name))
        else:
            result["unknown"].append(str(name))

    for values in result.values():
        values.sort()
    return result


def component_names(block: Any) -> list[str]:
    if isinstance(block, dict):
        return sorted(str(key) for key in block.keys())
    return []


def read_header_and_numeric(path: Path) -> ChainFileAudit:
    header: list[str] | None = None
    rows = 0
    ncols: int | None = None
    first_row_columns = 0
    finite = True
    positive_weights = True
    total_weight = 0.0
    total_weight_sq = 0.0

    with path.open("r", encoding="utf-8") as handle:
        for raw in handle:
            stripped = raw.strip()
            if not stripped:
                continue
            if stripped.startswith("#"):
                if header is None:
                    header = stripped.lstrip("#").split()
                continue

            parts = stripped.split()
            if ncols is None:
                ncols = len(parts)
                first_row_columns = ncols
            elif len(parts) != ncols:
                raise RuntimeError(
                    f"{path}: inconsistent column count at data row {rows + 1}: "
                    f"expected {ncols}, found {len(parts)}"
                )

            values = np.fromstring(stripped, sep=" ")
            if values.size != len(parts):
                raise RuntimeError(
                    f"{path}: failed to parse numeric data row {rows + 1}"
                )
            if not np.all(np.isfinite(values)):
                finite = False

            weight = float(values[0])
            if not (weight > 0.0 and math.isfinite(weight)):
                positive_weights = False
            total_weight += weight
            total_weight_sq += weight * weight
            rows += 1

    if header is None:
        raise RuntimeError(f"{path}: no Cobaya header line found")
    if ncols is None or rows == 0:
        raise RuntimeError(f"{path}: no numeric samples found")
    if len(header) != ncols:
        raise RuntimeError(
            f"{path}: header has {len(header)} columns but data have {ncols}"
        )

    ess = (
        total_weight * total_weight / total_weight_sq
        if total_weight_sq > 0.0
        else 0.0
    )
    match = CHAIN_RE.match(path.name)
    if not match:
        raise RuntimeError(f"Unrecognized chain filename: {path.name}")

    return ChainFileAudit(
        path=str(path),
        chain_number=int(match.group("number")),
        rows=rows,
        columns=ncols,
        header_columns=header,
        first_row_columns=first_row_columns,
        all_rows_finite=finite,
        positive_weights=positive_weights,
        total_weight=total_weight,
        weight_ess=ess,
    )


def parse_progress_value(item: str) -> float | str:
    """Parse numeric progress entries while preserving timestamps and labels."""
    try:
        return float(item)
    except ValueError:
        return item


def parse_progress(path: Path | None) -> dict[str, Any] | None:
    if path is None or not path.exists():
        return None

    header: list[str] | None = None
    rows: list[list[float | str]] = []
    with path.open("r", encoding="utf-8") as handle:
        for raw in handle:
            stripped = raw.strip()
            if not stripped:
                continue
            if stripped.startswith("#"):
                if header is None:
                    header = stripped.lstrip("#").split()
                continue
            values = [
                parse_progress_value(item)
                for item in stripped.split()
            ]
            rows.append(values)

    result: dict[str, Any] = {
        "path": str(path),
        "rows": len(rows),
        "columns": header or [],
    }
    if header and rows and len(header) == len(rows[-1]):
        # Progress files may include ISO timestamps as well as numeric
        # convergence/runtime diagnostics. Preserve both without coercion.
        result["final_diagnostics"] = {
            key: value for key, value in zip(header, rows[-1])
        }
    return result


def optional_file(root: Path, suffix: str) -> Path | None:
    path = Path(f"{root}{suffix}")
    return path if path.exists() else None


def find_chain_files(root: Path) -> list[Path]:
    parent = root.parent
    prefix = root.name
    candidates: list[tuple[int, Path]] = []
    for path in parent.glob(f"{prefix}.*.txt"):
        match = CHAIN_RE.match(path.name)
        if match and match.group("root") == prefix:
            candidates.append((int(match.group("number")), path))
    return [path for _, path in sorted(candidates)]


def names_present(columns: Iterable[str], candidates: set[str]) -> list[str]:
    return sorted(set(columns).intersection(candidates))


def audit_chain(extracted_root: Path, stem: str) -> dict[str, Any]:
    base = extracted_root / stem
    if not base.exists():
        raise RuntimeError(f"Missing extracted directory: {base}")

    updated = find_one(base, f"{stem}.updated.yaml")
    root = root_from_updated_yaml(updated)
    info = read_yaml(updated)

    input_yaml = optional_file(root, ".input.yaml")
    progress = optional_file(root, ".progress")
    covmat = optional_file(root, ".covmat")
    checkpoint = optional_file(root, ".checkpoint")
    paramnames = optional_file(root, ".paramnames")

    chain_paths = find_chain_files(root)
    if not chain_paths:
        raise RuntimeError(f"No numbered chain text files found for {root}")

    chain_audits = [read_header_and_numeric(path) for path in chain_paths]
    reference_header = chain_audits[0].header_columns
    headers_match = all(
        audit.header_columns == reference_header for audit in chain_audits
    )

    likelihoods = component_names(info.get("likelihood"))
    theories = component_names(info.get("theory"))
    samplers = component_names(info.get("sampler"))
    expected = EXPECTED[stem]

    total_rows = sum(item.rows for item in chain_audits)
    total_weight = sum(item.total_weight for item in chain_audits)
    total_weight_sq_equivalent = sum(
        (item.total_weight ** 2 / item.weight_ess)
        for item in chain_audits
        if item.weight_ess > 0
    )
    combined_weight_ess = (
        total_weight * total_weight / total_weight_sq_equivalent
        if total_weight_sq_equivalent > 0
        else 0.0
    )

    checks = {
        "updated_yaml_found": updated.exists(),
        "input_yaml_found": input_yaml is not None,
        "progress_file_found": progress is not None,
        "chain_files_found": len(chain_paths) > 0,
        "headers_match_across_chains": headers_match,
        "all_rows_finite": all(item.all_rows_finite for item in chain_audits),
        "all_weights_positive": all(item.positive_weights for item in chain_audits),
        "likelihood_block_matches_expected":
            set(likelihoods) == set(expected["likelihoods"]),
        "theory_block_matches_expected":
            set(theories) == set(expected["theory"]),
        "mcmc_sampler_declared": "mcmc" in samplers,
        "weight_column_first":
            bool(reference_header) and reference_header[0] == "weight",
        "minuslogpost_column_second":
            len(reference_header) > 1
            and reference_header[1] == "minuslogpost",
    }

    result = {
        "stem": stem,
        "root": str(root),
        "metadata": {
            "updated_yaml": str(updated),
            "input_yaml": str(input_yaml) if input_yaml else None,
            "progress": str(progress) if progress else None,
            "covmat": str(covmat) if covmat else None,
            "checkpoint": str(checkpoint) if checkpoint else None,
            "paramnames": str(paramnames) if paramnames else None,
        },
        "declared_components": {
            "likelihoods": likelihoods,
            "theories": theories,
            "samplers": samplers,
        },
        "expected_components": {
            "likelihoods": sorted(expected["likelihoods"]),
            "theories": sorted(expected["theory"]),
        },
        "parameter_classification": classify_params(info.get("params")),
        "column_names": reference_header,
        "needed_parameter_name_candidates": {
            "H0": names_present(reference_header, H0_NAMES),
            "age": names_present(reference_header, AGE_NAMES),
            "Omega_Lambda": names_present(reference_header, OMEGA_LAMBDA_NAMES),
            "Omega_m": names_present(reference_header, OMEGA_M_NAMES),
        },
        "sample_files": [item.__dict__ for item in chain_audits],
        "sample_totals": {
            "chains": len(chain_audits),
            "rows": total_rows,
            "total_weight": total_weight,
            "combined_weight_ess": combined_weight_ess,
        },
        "progress": parse_progress(progress),
        "official_external_burnin_fraction": (
            expected["official_external_burnin_fraction"]
        ),
        "official_burnin_note": (
            "The official ACT DR6.02 table displays no numeric burn-in "
            "fraction for this exact chain. This audit records that fact "
            "without converting the blank cell into an unstated number."
        ),
        "checks": checks,
        "pass": all(checks.values()),
    }
    return result


def write_report(summary: dict[str, Any], path: Path) -> None:
    sections: list[str] = [
        "# ACT DR6.02 chain-structure audit",
        "",
        f"Overall status: **{'PASS' if summary['overall_pass'] else 'FAIL'}**",
        "",
        "This audit did not calculate cosmological posterior summaries, "
        "`delta_Phi`, Bayes factors, or a scientific verdict.",
        "",
    ]

    for chain in summary["chains"]:
        totals = chain["sample_totals"]
        candidates = chain["needed_parameter_name_candidates"]
        sections.extend([
            f"## `{chain['stem']}`",
            "",
            f"- Chain files: `{totals['chains']}`",
            f"- Stored rows: `{totals['rows']}`",
            f"- Weight ESS before any external row exclusion: "
            f"`{totals['combined_weight_ess']:.1f}`",
            f"- Declared likelihoods: "
            f"`{', '.join(chain['declared_components']['likelihoods'])}`",
            f"- Declared theory: "
            f"`{', '.join(chain['declared_components']['theories'])}`",
            f"- H0-name candidates: `{candidates['H0']}`",
            f"- Age-name candidates: `{candidates['age']}`",
            f"- Omega-Lambda-name candidates: `{candidates['Omega_Lambda']}`",
            f"- Omega-m-name candidates: `{candidates['Omega_m']}`",
            f"- Official external burn-in entry: "
            f"`{chain['official_external_burnin_fraction']}` "
            "(blank/not numerically specified in the ACT table)",
            f"- Status: **{'PASS' if chain['pass'] else 'FAIL'}**",
            "",
            "Checks:",
            "",
            "```json",
            json.dumps(chain["checks"], indent=2, sort_keys=True),
            "```",
            "",
        ])

    sections.extend([
        "## Overall checks",
        "",
        "```json",
        json.dumps(summary["checks"], indent=2, sort_keys=True),
        "```",
        "",
    ])
    path.write_text("\n".join(sections), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--extracted-root",
        type=Path,
        default=Path("data/derived/act_dr6_02/chains"),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("results/provenance/phase1_chain_audit"),
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Deliberately replace an earlier audit directory.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    output_dir = args.output_dir.resolve()

    if output_dir.exists() and not args.overwrite:
        print(
            f"ERROR: {output_dir} already exists; use --overwrite deliberately.",
            file=sys.stderr,
        )
        return 2
    output_dir.mkdir(parents=True, exist_ok=True)

    chains: list[dict[str, Any]] = []
    errors: list[str] = []
    for stem in EXPECTED:
        try:
            chains.append(audit_chain(args.extracted_root.resolve(), stem))
        except Exception as exc:
            errors.append(f"{stem}: {type(exc).__name__}: {exc}")

    checks = {
        "all_three_expected_chains_audited": len(chains) == len(EXPECTED),
        "all_chain_audits_pass": bool(chains) and all(c["pass"] for c in chains),
        "no_audit_errors": not errors,
        "no_golden_ratio_statistic_computed": True,
    }
    overall_pass = all(checks.values())

    summary = {
        "audit": "ACT DR6.02 chain structure and ingestion preflight",
        "chains": chains,
        "errors": errors,
        "checks": checks,
        "overall_pass": overall_pass,
    }

    json_path = output_dir / "chain_structure_audit.json"
    report_path = output_dir / "REPORT.md"
    json_path.write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    write_report(summary, report_path)

    print(f"Summary: {json_path}")
    print(f"Report:  {report_path}")
    print(f"Overall: {'PASS' if overall_pass else 'FAIL'}")
    if errors:
        print("Errors:")
        for error in errors:
            print(f"  - {error}")
    return 0 if overall_pass else 1


if __name__ == "__main__":
    raise SystemExit(main())
