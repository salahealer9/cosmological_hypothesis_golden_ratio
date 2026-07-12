#!/usr/bin/env python3

from __future__ import annotations

import json
from pathlib import Path

import yaml


STEMS = (
    "planck_lcdm_camb",
    "actlite_lcdm_camb",
    "p-actlite_lcdm_camb",
)

ROOT = Path("data/derived/act_dr6_02/chains")
OUTPUT = Path(
    "results/provenance/phase1_parameter_schema/"
    "parameter_schema.json"
)


def load_yaml(path: Path):
    with path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def first_chain_header(root: Path) -> list[str]:
    files = sorted(root.parent.glob(f"{root.name}.*.txt"))
    numbered = [
        path for path in files
        if path.name.rsplit(".", 2)[-2].isdigit()
    ]

    if not numbered:
        raise RuntimeError(f"No numbered chain files found for {root}")

    with numbered[0].open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.startswith("#"):
                return line.lstrip("#").split()

    raise RuntimeError(f"No header found in {numbered[0]}")


def classify_params(params):
    result = {
        "sampled": {},
        "derived": {},
        "fixed": {},
        "other": {},
    }

    for name, spec in (params or {}).items():
        if isinstance(spec, dict) and "prior" in spec:
            result["sampled"][name] = spec
        elif isinstance(spec, dict) and (
            spec.get("derived") is True
            or "value" in spec
        ):
            result["derived"][name] = spec
        elif not isinstance(spec, dict):
            result["fixed"][name] = spec
        else:
            result["other"][name] = spec

    return result


def main():
    report = {}

    for stem in STEMS:
        base = ROOT / stem
        updated_files = list(base.rglob(f"{stem}.updated.yaml"))

        if len(updated_files) != 1:
            raise RuntimeError(
                f"{stem}: expected one updated YAML, "
                f"found {len(updated_files)}"
            )

        updated = updated_files[0]
        chain_root = Path(
            str(updated).removesuffix(".updated.yaml")
        )
        config = load_yaml(updated)

        report[stem] = {
            "updated_yaml": str(updated),
            "chain_root": str(chain_root),
            "chain_columns": first_chain_header(chain_root),
            "parameters": classify_params(config.get("params")),
            "theory": config.get("theory", {}),
            "likelihood": config.get("likelihood", {}),
            "sampler": config.get("sampler", {}),
        }

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    print(f"Wrote {OUTPUT}")

    for stem, info in report.items():
        print(f"\n=== {stem} ===")

        print("\nChain columns:")
        print("  " + "\n  ".join(info["chain_columns"]))

        print("\nSampled parameters:")
        for name in info["parameters"]["sampled"]:
            print(f"  {name}")

        print("\nDerived parameters declared in YAML:")
        for name in info["parameters"]["derived"]:
            print(f"  {name}")

        print("\nFixed parameters:")
        for name, value in info["parameters"]["fixed"].items():
            print(f"  {name} = {value!r}")

        print("\nTheory configuration:")
        print(
            json.dumps(
                info["theory"],
                indent=2,
                sort_keys=True,
                default=str,
            )
        )


if __name__ == "__main__":
    main()
