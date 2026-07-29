#!/usr/bin/env python3
"""Inventory dependency licenses and fail closed on unknown or unapproved terms."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from collections import deque
from importlib.metadata import PackageMetadata, distributions
from pathlib import Path

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

ROOT = Path(__file__).resolve().parents[1]
APPROVED_LICENSES = {
    "0BSD",
    "Apache-2.0",
    "Apache-2.0 AND LGPL-3.0-or-later",
    "Apache-2.0 OR BSD-2-Clause",
    "Apache-2.0 OR BSD-3-Clause",
    "BSD-2-Clause",
    "BSD-3-Clause",
    "BlueOak-1.0.0",
    "CC-BY-4.0",
    "ISC",
    "MIT",
    "MIT AND Python-2.0",
    "MIT AND PSF-2.0",
    "MIT-CMU",
    "MIT OR Apache-2.0",
    "MIT-0",
    "MPL-2.0",
    "ODC-By-1.0",
    "PSF-2.0",
    "Python-2.0",
}
NOTICE_REQUIRED_LICENSES = {"BlueOak-1.0.0", "ODC-By-1.0", "Python-2.0"}
THIRD_PARTY_NOTICES = ROOT / "THIRD_PARTY_NOTICES.md"
LICENSE_NORMALIZATION = {
    "Apache 2": "Apache-2.0",
    "Apache 2.0": "Apache-2.0",
    "Apache License, Version 2.0": "Apache-2.0",
    "Apache Software License": "Apache-2.0",
    "BSD 3-Clause License": "BSD-3-Clause",
    "BSD License": "BSD-3-Clause",
    "MIT License": "MIT",
    "The MIT License (MIT)": "MIT",
}
CLASSIFIER_LICENSES = {
    "Apache Software License": "Apache-2.0",
    "BSD License": "BSD-3-Clause",
    "MIT License": "MIT",
    "Mozilla Public License 2.0 (MPL 2.0)": "MPL-2.0",
    "Python Software Foundation License": "PSF-2.0",
}
IGNORED_PYTHON_TOOLS = {"pip", "setuptools", "wheel"}
PYTHON_REQUIREMENTS = ROOT / "apps" / "api" / "requirements-dev.txt"


def python_license(metadata: PackageMetadata) -> str | None:
    expression = metadata.get("License-Expression")
    if expression and expression.strip().lower() not in {"unknown", "none"}:
        return LICENSE_NORMALIZATION.get(expression.strip(), expression.strip())
    value = metadata.get("License")
    if value and value.strip().lower() not in {"unknown", "none"}:
        stripped = value.strip()
        normalized = LICENSE_NORMALIZATION.get(stripped)
        if normalized:
            return normalized
        if "\n" not in stripped and len(stripped) <= 128:
            return stripped
    found = {
        CLASSIFIER_LICENSES[classifier.rsplit(" :: ", 1)[-1]]
        for classifier in metadata.get_all("Classifier", [])
        if classifier.rsplit(" :: ", 1)[-1] in CLASSIFIER_LICENSES
    }
    return " OR ".join(sorted(found)) if found else None


def requirement_roots(path: Path = PYTHON_REQUIREMENTS) -> list[Requirement]:
    roots: list[Requirement] = []
    visited: set[Path] = set()

    def visit(requirements_file: Path) -> None:
        resolved = requirements_file.resolve()
        if resolved in visited:
            return
        visited.add(resolved)
        if not resolved.is_file():
            raise RuntimeError(f"requirements file is missing: {resolved}")
        for raw_line in resolved.read_text(encoding="utf-8").splitlines():
            line = raw_line.split("#", 1)[0].strip()
            if not line:
                continue
            if line.startswith(("-r ", "--requirement ")):
                nested = line.split(maxsplit=1)[1]
                visit(resolved.parent / nested)
                continue
            if line.startswith("-"):
                raise RuntimeError(f"unsupported requirement directive: {line}")
            roots.append(Requirement(line))

    visit(path)
    return roots


def requirement_applies(requirement: Requirement, extras: frozenset[str]) -> bool:
    if requirement.marker is None:
        return True
    candidates = extras or frozenset({""})
    return any(requirement.marker.evaluate({"extra": extra}) for extra in candidates)


def python_dependency_names(
    roots: list[Requirement], available: dict[str, object]
) -> set[str]:
    selected: set[str] = set()
    processed: set[tuple[str, frozenset[str]]] = set()
    queue = deque(
        (canonicalize_name(requirement.name), frozenset(requirement.extras))
        for requirement in roots
        if requirement.marker is None or requirement.marker.evaluate({"extra": ""})
    )
    while queue:
        name, extras = queue.popleft()
        state = (name, extras)
        if state in processed:
            continue
        processed.add(state)
        distribution = available.get(name)
        if distribution is None:
            raise RuntimeError(f"required Python distribution is not installed: {name}")
        selected.add(name)
        metadata = distribution.metadata
        for raw_requirement in metadata.get_all("Requires-Dist", []):
            requirement = Requirement(raw_requirement)
            if requirement_applies(requirement, extras):
                queue.append(
                    (
                        canonicalize_name(requirement.name),
                        frozenset(requirement.extras),
                    )
                )
    return selected


def python_inventory() -> list[dict[str, str]]:
    available = {
        canonicalize_name(distribution.metadata.get("Name") or "unknown"): distribution
        for distribution in distributions()
    }
    selected = python_dependency_names(requirement_roots(), available)
    packages: list[dict[str, str]] = []
    for canonical_name in selected:
        distribution = available[canonical_name]
        name = distribution.metadata.get("Name") or "unknown"
        if name.lower() in IGNORED_PYTHON_TOOLS:
            continue
        packages.append(
            {
                "ecosystem": "python",
                "name": name,
                "version": distribution.version,
                "license": python_license(distribution.metadata) or "UNKNOWN",
            }
        )
    return sorted(packages, key=lambda item: item["name"].lower())


def node_inventory() -> list[dict[str, str]]:
    pnpm = shutil.which("pnpm")
    if not pnpm:
        raise RuntimeError("pnpm is required for the Node dependency license inventory")
    completed = subprocess.run(
        [pnpm, "licenses", "list", "--json"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    grouped = json.loads(completed.stdout)
    packages: list[dict[str, str]] = []
    for license_name, items in grouped.items():
        normalized = LICENSE_NORMALIZATION.get(license_name, license_name)
        for item in items:
            for version in item.get("versions", ["unknown"]):
                packages.append(
                    {
                        "ecosystem": "node",
                        "name": item["name"],
                        "version": version,
                        "license": normalized,
                    }
                )
    return sorted(packages, key=lambda item: (item["name"].lower(), item["version"]))


def decode_json_stream(value: str) -> list[dict[str, object]]:
    decoder = json.JSONDecoder()
    offset = 0
    items: list[dict[str, object]] = []
    while offset < len(value):
        while offset < len(value) and value[offset].isspace():
            offset += 1
        if offset >= len(value):
            break
        item, offset = decoder.raw_decode(value, offset)
        items.append(item)
    return items


def go_inventory() -> list[dict[str, str]]:
    completed = subprocess.run(
        ["go", "list", "-m", "-json", "all"],
        cwd=ROOT / "apps" / "agent",
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    modules = decode_json_stream(completed.stdout)
    dependencies = [item for item in modules if not item.get("Main")]
    return [
        {
            "ecosystem": "go",
            "name": str(item["Path"]),
            "version": str(item.get("Version", "unknown")),
            "license": "UNKNOWN",
        }
        for item in dependencies
    ]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    packages = python_inventory() + node_inventory() + go_inventory()
    rejected = [item for item in packages if item["license"] not in APPROVED_LICENSES]
    notice_text = (
        THIRD_PARTY_NOTICES.read_text(encoding="utf-8")
        if THIRD_PARTY_NOTICES.is_file()
        else ""
    )
    missing_notices = sorted(
        {
            item["license"]
            for item in packages
            if item["license"] in NOTICE_REQUIRED_LICENSES
            and item["license"] not in notice_text
        }
    )
    report = {
        "approved_license_expressions": sorted(APPROVED_LICENSES),
        "package_count": len(packages),
        "packages": packages,
        "rejected": rejected,
        "missing_notices": missing_notices,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    if rejected:
        for item in rejected:
            print(
                f"unapproved dependency license: {item['ecosystem']} "
                f"{item['name']} {item['version']} ({item['license']})",
                file=sys.stderr,
            )
        return 1
    if missing_notices:
        print(
            "missing third-party notices for: " + ", ".join(missing_notices),
            file=sys.stderr,
        )
        return 1
    print(f"dependency license policy passed for {len(packages)} packages")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
