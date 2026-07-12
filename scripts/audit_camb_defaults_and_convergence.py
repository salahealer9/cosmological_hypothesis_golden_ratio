#!/usr/bin/env python3
"""
Audit the exact CAMB 1.5.0 background defaults and released-chain convergence
metadata without reading cosmological posterior values.

This script does not compute delta_Phi or any posterior summary.
"""

from __future__ import annotations

import inspect
import json
import math
import sys
from importlib.metadata import version
from pathlib import Path
from typing import Any

import camb
from camb import constants, model


CHAIN_STEMS = (
    "planck_lcdm_camb",
    "actlite_lcdm_camb",
    "p-actlite_lcdm_camb",
)

CHAIN_AUDIT = Path(
    "results/provenance/phase1_chain_audit/chain_structure_audit.json"
)
SCHEMA_AUDIT = Path(
    "results/provenance/phase1_parameter_schema/parameter_schema.json"
)
OUTPUT_DIR = Path(
    "results/provenance/phase1_camb_defaults_and_convergence"
)


def jsonable(value: Any) -> Any:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, dict):
        return {str(k): jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [jsonable(v) for v in value]
    try:
        return float(value)
    except (TypeError, ValueError):
        return repr(value)


def set_cosmology_defaults() -> dict[str, Any]:
    signature = inspect.signature(model.CAMBparams.set_cosmology)
    result: dict[str, Any] = {}
    for name, parameter in signature.parameters.items():
        if name == "self":
            continue
        default = parameter.default
        if default is inspect.Parameter.empty:
            result[name] = "REQUIRED"
        else:
            result[name] = jsonable(default)
    return result


def nominal_background_audit() -> dict[str, Any]:
    # Arbitrary non-posterior nominal point used only to expose defaults.
    pars = camb.CAMBparams()
    pars.set_cosmology(
        H0=67.0,
        ombh2=0.022,
        omch2=0.12,
    )

    derived = camb.get_background(pars).get_derived_params()

    massive_degeneracies = [
        float(pars.nu_mass_degeneracies[i])
        for i in range(int(pars.nu_mass_eigenstates))
    ]
    massive_fractions = [
        float(pars.nu_mass_fractions[i])
        for i in range(int(pars.nu_mass_eigenstates))
    ]
    massive_numbers = [
        int(pars.nu_mass_numbers[i])
        for i in range(int(pars.nu_mass_eigenstates))
    ]

    return {
        "nominal_inputs": {
            "H0": 67.0,
            "ombh2": 0.022,
            "omch2": 0.12,
        },
        "resolved_background": {
            "H0": float(pars.H0),
            "ombh2": float(pars.ombh2),
            "omch2": float(pars.omch2),
            "omk": float(pars.omk),
            "omnuh2": float(pars.omnuh2),
            "TCMB": float(pars.TCMB),
            "num_nu_massless": float(pars.num_nu_massless),
            "num_nu_massive": int(pars.num_nu_massive),
            "nu_mass_eigenstates": int(pars.nu_mass_eigenstates),
            "nu_mass_degeneracies": massive_degeneracies,
            "nu_mass_fractions": massive_fractions,
            "nu_mass_numbers": massive_numbers,
            "dark_energy_class": type(pars.DarkEnergy).__name__,
            "w": float(pars.DarkEnergy.w),
            "wa": float(pars.DarkEnergy.wa),
        },
        "derived_background_only": {
            key: float(value)
            for key, value in derived.items()
            if isinstance(value, (int, float))
        },
    }


def sampler_and_progress_audit() -> dict[str, Any]:
    schema = json.loads(SCHEMA_AUDIT.read_text(encoding="utf-8"))
    chain_audit = json.loads(CHAIN_AUDIT.read_text(encoding="utf-8"))
    by_stem = {entry["stem"]: entry for entry in chain_audit["chains"]}

    result: dict[str, Any] = {}
    for stem in CHAIN_STEMS:
        progress = by_stem[stem].get("progress")
        result[stem] = {
            "sampler": schema[stem].get("sampler", {}),
            "progress": progress,
            "official_external_burnin_fraction": by_stem[stem].get(
                "official_external_burnin_fraction"
            ),
        }
    return result


def checks(report: dict[str, Any]) -> dict[str, bool]:
    resolved = report["nominal_default_resolution"]["resolved_background"]
    return {
        "camb_version_is_1_5_0": report["software"]["camb"] == "1.5.0",
        "flat_default": abs(resolved["omk"]) < 1e-15,
        "one_massive_neutrino_default": resolved["num_nu_massive"] == 1,
        "positive_massive_neutrino_density": resolved["omnuh2"] > 0.0,
        "lambda_default_w": abs(resolved["w"] + 1.0) < 1e-15,
        "lambda_default_wa": abs(resolved["wa"]) < 1e-15,
        "all_three_chain_sampler_blocks_present": all(
            bool(report["released_chain_metadata"][stem]["sampler"])
            for stem in CHAIN_STEMS
        ),
        "all_three_progress_blocks_present": all(
            report["released_chain_metadata"][stem]["progress"] is not None
            for stem in CHAIN_STEMS
        ),
        "no_golden_ratio_statistic_computed": True,
    }


def main() -> int:
    if not CHAIN_AUDIT.exists():
        raise SystemExit(f"Missing {CHAIN_AUDIT}")
    if not SCHEMA_AUDIT.exists():
        raise SystemExit(f"Missing {SCHEMA_AUDIT}")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    report = {
        "audit": "CAMB 1.5.0 defaults and released-chain convergence metadata",
        "software": {
            "python": sys.version.split()[0],
            "camb": version("camb"),
        },
        "constants": {
            "default_nnu": float(constants.default_nnu),
            "COBE_CMBTemp": float(constants.COBE_CMBTemp),
        },
        "set_cosmology_signature_defaults": set_cosmology_defaults(),
        "nominal_default_resolution": nominal_background_audit(),
        "released_chain_metadata": sampler_and_progress_audit(),
    }
    report["checks"] = checks(report)
    report["overall_pass"] = all(report["checks"].values())

    json_path = OUTPUT_DIR / "audit.json"
    report_path = OUTPUT_DIR / "REPORT.md"

    json_path.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    resolved = report["nominal_default_resolution"]["resolved_background"]
    lines = [
        "# CAMB defaults and chain-convergence audit",
        "",
        f"Overall status: **{'PASS' if report['overall_pass'] else 'FAIL'}**",
        "",
        "No posterior central values or golden-ratio residuals were computed.",
        "",
        "## Exact software and constants",
        "",
        f"- CAMB: `{report['software']['camb']}`",
        f"- `default_nnu`: `{report['constants']['default_nnu']}`",
        f"- `COBE_CMBTemp`: `{report['constants']['COBE_CMBTemp']}` K",
        "",
        "## Resolved default background",
        "",
        f"- `omk`: `{resolved['omk']}`",
        f"- `omnuh2`: `{resolved['omnuh2']}`",
        f"- `num_nu_massless`: `{resolved['num_nu_massless']}`",
        f"- `num_nu_massive`: `{resolved['num_nu_massive']}`",
        f"- `nu_mass_eigenstates`: `{resolved['nu_mass_eigenstates']}`",
        f"- dark-energy class: `{resolved['dark_energy_class']}`",
        f"- `w`: `{resolved['w']}`",
        f"- `wa`: `{resolved['wa']}`",
        "",
        "## Released-chain sampler/progress metadata",
        "",
    ]

    for stem in CHAIN_STEMS:
        metadata = report["released_chain_metadata"][stem]
        final = (
            metadata.get("progress", {})
            .get("final_diagnostics", {})
            if metadata.get("progress")
            else {}
        )
        lines.extend([
            f"### `{stem}`",
            "",
            "Sampler:",
            "",
            "```json",
            json.dumps(metadata["sampler"], indent=2, sort_keys=True),
            "```",
            "",
            "Final progress diagnostics:",
            "",
            "```json",
            json.dumps(final, indent=2, sort_keys=True),
            "```",
            "",
        ])

    lines.extend([
        "## Checks",
        "",
        "```json",
        json.dumps(report["checks"], indent=2, sort_keys=True),
        "```",
        "",
    ])
    report_path.write_text("\n".join(lines), encoding="utf-8")

    print(f"Summary: {json_path}")
    print(f"Report:  {report_path}")
    print(f"Overall: {'PASS' if report['overall_pass'] else 'FAIL'}")
    return 0 if report["overall_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
