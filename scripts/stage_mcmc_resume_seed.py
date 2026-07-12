#!/usr/bin/env python3

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import yaml


MANIFEST = Path(
    "results/provenance/"
    "phase1_chain_rerun_manifest.json"
)

TARGET = Path(
    "data/derived/act_dr6_02/"
    "mcmc_extension_seed"
)

PROVENANCE = Path(
    "results/provenance/"
    "mcmc_extension_seed_map.json"
)

CHECKSUMS = Path(
    "results/provenance/"
    "mcmc-extension-seed-checksums.txt"
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()

    with path.open("rb") as handle:
        for block in iter(
            lambda: handle.read(1024 * 1024),
            b"",
        ):
            digest.update(block)

    return digest.hexdigest()


def main() -> None:
    if TARGET.exists():
        raise SystemExit(
            f"{TARGET} already exists; refusing to overwrite."
        )

    manifest = json.loads(
        MANIFEST.read_text(encoding="utf-8")
    )

    records = {}

    for stem, entry in manifest.items():
        source_root = Path(entry["root"])
        output_prefix = entry["output_in_yaml"]

        if not output_prefix:
            raise RuntimeError(
                f"{stem}: missing output prefix"
            )

        source_files = sorted(
            path
            for path in source_root.parent.glob(
                f"{source_root.name}.*"
            )
            if path.is_file()
        )

        if not source_files:
            raise RuntimeError(
                f"{stem}: no source-root files found"
            )

        destination = TARGET / stem
        destination.mkdir(parents=True)

        copied = []

        for source in source_files:
            suffix = source.name[
                len(source_root.name):
            ]

            target = destination / (
                output_prefix + suffix
            )

            shutil.copy2(source, target)

            copied.append({
                "source": str(source),
                "destination": str(target),
                "source_sha256": sha256(source),
                "copied_sha256": sha256(target),
            })

            if copied[-1]["source_sha256"] != \
                    copied[-1]["copied_sha256"]:
                raise RuntimeError(
                    f"Copy verification failed: {source}"
                )

        for suffix in (
            ".input.yaml",
            ".updated.yaml",
        ):
            metadata_path = destination / (
                output_prefix + suffix
            )

            metadata = yaml.safe_load(
                metadata_path.read_text(
                    encoding="utf-8"
                )
            )

            if metadata.get("output") != output_prefix:
                raise RuntimeError(
                    f"{metadata_path}: output is "
                    f"{metadata.get('output')!r}, "
                    f"expected {output_prefix!r}"
                )

        checkpoint_path = destination / (
            output_prefix + ".checkpoint"
        )

        checkpoint = yaml.safe_load(
            checkpoint_path.read_text(
                encoding="utf-8"
            )
        )

        state = checkpoint["sampler"]["mcmc"]

        original_checkpoint = {
            "converged": state["converged"],
            "Rminus1_last": state["Rminus1_last"],
            "burn_in": state["burn_in"],
            "mpi_size": state["mpi_size"],
        }

        if state["mpi_size"] != 4:
            raise RuntimeError(
                f"{stem}: expected mpi_size 4"
            )

        # Operational reset in the copied workspace only.
        # The released checkpoint remains untouched.
        state["converged"] = False

        checkpoint_path.write_text(
            yaml.safe_dump(
                checkpoint,
                sort_keys=False,
            ),
            encoding="utf-8",
        )

        numbered = sorted(
            destination.glob(
                f"{output_prefix}.[0-9]*.txt"
            )
        )

        if len(numbered) != 4:
            raise RuntimeError(
                f"{stem}: expected four numbered "
                f"chains, found {len(numbered)}"
            )

        records[stem] = {
            "source_root": str(source_root),
            "destination_directory":
                str(destination),
            "output_prefix": output_prefix,
            "original_checkpoint":
                original_checkpoint,
            "copied_checkpoint_converged":
                False,
            "numbered_chain_count":
                len(numbered),
            "copied_files": copied,
        }

    PROVENANCE.write_text(
        json.dumps(
            records,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    checksum_lines = []

    for path in sorted(TARGET.rglob("*")):
        if path.is_file():
            checksum_lines.append(
                f"{sha256(path)}  {path}"
            )

    CHECKSUMS.write_text(
        "\n".join(checksum_lines) + "\n",
        encoding="utf-8",
    )

    print(f"Staged: {TARGET}")
    print(f"Map: {PROVENANCE}")
    print(f"Checksums: {CHECKSUMS}")

    for stem, record in records.items():
        print()
        print(stem)
        print(
            "  prefix:",
            record["output_prefix"],
        )
        print(
            "  original converged:",
            record["original_checkpoint"][
                "converged"
            ],
        )
        print(
            "  copied converged:",
            record[
                "copied_checkpoint_converged"
            ],
        )
        print(
            "  MPI size:",
            record["original_checkpoint"][
                "mpi_size"
            ],
        )


if __name__ == "__main__":
    main()
