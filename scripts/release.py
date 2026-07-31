#!/usr/bin/env python3
"""Validate and assemble the immutable self-hosted release bundle."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import re
import shutil
import subprocess
import tarfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC_PATH = ROOT / "release" / "release.json"
SEMVER = re.compile(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")
DIGEST = re.compile(r"^(?P<repository>[a-z0-9.-]+(?::[0-9]+)?/[a-z0-9._/-]+)@sha256:(?P<digest>[0-9a-f]{64})$")
PINNED_ACTION = re.compile(r"^[^@\s]+@[0-9a-f]{40}$")
REQUIRED_BUNDLE_FILES = (
    "LICENSE",
    "LICENSING.md",
    "NOTICE",
    "THIRD_PARTY_NOTICES.md",
    "CHANGELOG.md",
    "release/release.json",
    "docs/RELEASE_COMPATIBILITY.md",
    "docs/RELEASE_PROCESS.md",
    "deploy/compose.production.yaml",
    "deploy/release/compose.release.yaml",
    "deploy/release/.env.release.example",
    "deploy/.env.production.example",
    "deploy/caddy/Caddyfile",
    "deploy/control-plane-release.sh",
    "deploy/control-plane-backup.sh",
    "deploy/control-plane-restore.sh",
)


class ReleaseError(RuntimeError):
    pass


def load_spec(root: Path = ROOT) -> dict[str, object]:
    try:
        value = json.loads((root / "release" / "release.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ReleaseError(f"invalid release specification: {error}") from error
    if not isinstance(value, dict):
        raise ReleaseError("release specification must be a JSON object")
    return value


def git_output(root: Path, *args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=root, text=True).strip()


def validate_action_pins(root: Path) -> list[str]:
    errors: list[str] = []
    for workflow in sorted((root / ".github" / "workflows").glob("*.yml")):
        for line_number, line in enumerate(workflow.read_text(encoding="utf-8").splitlines(), 1):
            match = re.search(r"\buses:\s*([^\s#]+)", line)
            if not match or match.group(1).startswith("./"):
                continue
            if not PINNED_ACTION.fullmatch(match.group(1)):
                relative = workflow.relative_to(root).as_posix()
                errors.append(f"{relative}:{line_number}: Action is not pinned to a full commit")
    return errors


def validate_spec(root: Path = ROOT, expected_version: str | None = None) -> dict[str, object]:
    spec = load_spec(root)
    errors: list[str] = []
    version = spec.get("version")
    tag = spec.get("tag")
    repository = spec.get("repository")
    agent_module = spec.get("agent_module")
    images = spec.get("images")
    build_images = spec.get("build_images")
    runtime_images = spec.get("runtime_images")
    schema_revision = spec.get("schema_revision")

    if not isinstance(version, str) or not SEMVER.fullmatch(version):
        errors.append("release version must be canonical MAJOR.MINOR.PATCH")
    if tag != f"v{version}":
        errors.append("release tag must equal v + version")
    if expected_version and version != expected_version.removeprefix("v"):
        errors.append("requested version does not match release/release.json")
    if repository != "github.com/ymasout/VPS-Agent":
        errors.append("repository coordinate is not frozen")
    if agent_module != f"{repository}/apps/agent":
        errors.append("Agent module does not match the repository coordinate")
    if not isinstance(images, dict) or images != {
        "api": "ghcr.io/ymasout/vps-agent-api",
        "web": "ghcr.io/ymasout/vps-agent-web",
    }:
        errors.append("OCI image coordinates are not frozen")
    for name, collection in (("build_images", build_images), ("runtime_images", runtime_images)):
        if not isinstance(collection, dict) or not collection:
            errors.append(f"{name} must contain digest-pinned images")
            continue
        for reference in collection.values():
            try:
                checked_image(str(reference))
            except ReleaseError as error:
                errors.append(f"{name}: {error}")
    if not isinstance(schema_revision, str) or len(schema_revision) > 32:
        errors.append("schema revision is missing or exceeds Alembic version_num")

    module = (root / "apps" / "agent" / "go.mod").read_text(encoding="utf-8").splitlines()[0]
    if module != f"module {agent_module}":
        errors.append("apps/agent/go.mod does not match the release Agent module")
    for path in (root / "apps" / "agent").rglob("*.go"):
        if "github.com/example/vps-agent-console" in path.read_text(encoding="utf-8"):
            errors.append(f"{path.relative_to(root)} still uses the placeholder Go module")

    migrations = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (root / "apps" / "api" / "migrations" / "versions").glob("*.py")
    )
    if f'revision = "{schema_revision}"' not in migrations:
        errors.append("release schema revision is not present in Alembic migrations")
    changelog = (root / "CHANGELOG.md").read_text(encoding="utf-8")
    if f"## [{version}] - Unreleased" not in changelog:
        errors.append("CHANGELOG does not describe the planned release")
    for package_file in (root / "package.json", root / "apps" / "web" / "package.json"):
        package = json.loads(package_file.read_text(encoding="utf-8"))
        if package.get("version") != version:
            errors.append(f"{package_file.relative_to(root).as_posix()} version does not match release version")
    agent_main = (root / "apps" / "agent" / "cmd" / "agent" / "main.go").read_text(encoding="utf-8")
    if f'var version = "{version}-dev"' not in agent_main:
        errors.append("Agent development version does not match the release line")

    override = (root / "deploy" / "release" / "compose.release.yaml").read_text(encoding="utf-8")
    for service, variable in {
        "api": "VPS_AGENT_API_IMAGE",
        "web": "VPS_AGENT_WEB_IMAGE",
        "caddy": "VPS_AGENT_CADDY_IMAGE",
        "postgres": "VPS_AGENT_POSTGRES_IMAGE",
        "redis": "VPS_AGENT_REDIS_IMAGE",
    }.items():
        if f"{service}:" not in override or f"${{{variable}:?" not in override:
            errors.append(f"release Compose does not require {variable}")
    if override.count("build: !reset null") != 2:
        errors.append("release Compose must remove exactly the API and Web build sections")

    formal_workflow = (root / ".github" / "workflows" / "formal-release.yml").read_text(encoding="utf-8")
    for required in (
        "workflow_dispatch:",
        "candidate-${{ inputs.commit_sha }}",
        "private-vulnerability-reporting",
        "public_ghcr_confirmed",
        "cosign verify",
        "--draft=false",
    ):
        if required not in formal_workflow:
            errors.append(f"formal release workflow is missing invariant: {required}")
    if re.search(r"^\s{2}push:\s*$", formal_workflow, re.MULTILINE):
        errors.append("formal release workflow must not trigger from a Git push")
    legacy_workflow = (root / ".github" / "workflows" / "release-agent.yml").read_text(encoding="utf-8")
    if "contents: write" in legacy_workflow or "gh release" in legacy_workflow:
        errors.append("Agent candidate workflow must remain review-only")

    api_dockerfile = (root / "apps" / "api" / "Dockerfile").read_text(encoding="utf-8")
    web_dockerfile = (root / "apps" / "web" / "Dockerfile").read_text(encoding="utf-8")
    if "@sha256:" not in api_dockerfile or "USER 10001:10001" not in api_dockerfile:
        errors.append("API release image must use a pinned base and non-root user")
    if "@sha256:" not in web_dockerfile or "USER node" not in web_dockerfile:
        errors.append("Web release image must use a pinned base and non-root user")
    installer = (root / "scripts" / "install-agent.sh").read_text(encoding="utf-8")
    if "cosign verify-blob" not in installer or "--allow-legacy-checksum-only" not in installer:
        errors.append("Agent installer must verify formal signatures and explicitly gate legacy bypass")
    if "VPS_AGENT_COSIGN_CERTIFICATE_IDENTITY" in installer or "VPS_AGENT_COSIGN_OIDC_ISSUER" in installer:
        errors.append("Agent installer must not allow release identity or issuer overrides")

    errors.extend(validate_action_pins(root))
    for relative in REQUIRED_BUNDLE_FILES:
        if not (root / relative).is_file():
            errors.append(f"required release file is missing: {relative}")
    if errors:
        raise ReleaseError("\n".join(errors))
    return spec


def checked_image(reference: str, expected_repository: str | None = None) -> str:
    match = DIGEST.fullmatch(reference)
    if not match:
        raise ReleaseError(f"image is not an immutable canonical digest reference: {reference}")
    if expected_repository and match.group("repository") != expected_repository:
        raise ReleaseError(f"image repository mismatch: expected {expected_repository}")
    return reference


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def build_deterministic_archive(bundle: Path, archive: Path, output_root: Path, epoch: int) -> None:
    def normalized(info: tarfile.TarInfo) -> tarfile.TarInfo:
        info.uid = 0
        info.gid = 0
        info.uname = ""
        info.gname = ""
        info.mtime = epoch
        return info

    with archive.open("wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=epoch) as compressed:
            with tarfile.open(fileobj=compressed, mode="w", format=tarfile.PAX_FORMAT) as tar:
                paths = [bundle, *sorted(bundle.rglob("*"), key=lambda path: path.as_posix())]
                for path in paths:
                    tar.add(
                        path,
                        arcname=path.relative_to(output_root),
                        recursive=False,
                        filter=normalized,
                    )


def build_bundle(args: argparse.Namespace, root: Path = ROOT) -> dict[str, object]:
    spec = validate_spec(root, args.version)
    version = str(spec["version"])
    status = git_output(root, "status", "--porcelain=v1")
    if status:
        raise ReleaseError("release bundle requires a clean committed worktree")
    head = git_output(root, "rev-parse", "HEAD")
    commit = args.commit or head
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ReleaseError("commit must be a full lowercase Git SHA")
    if commit != head:
        raise ReleaseError("release commit must equal the checked-out HEAD")
    api = checked_image(args.api_image, str(spec["images"]["api"]))  # type: ignore[index]
    web = checked_image(args.web_image, str(spec["images"]["web"]))  # type: ignore[index]
    runtime_images = spec["runtime_images"]
    if not isinstance(runtime_images, dict):
        raise ReleaseError("runtime_images must be an object")
    base_images = {
        "VPS_AGENT_CADDY_IMAGE": checked_image(args.caddy_image or str(runtime_images["caddy"])),
        "VPS_AGENT_POSTGRES_IMAGE": checked_image(args.postgres_image or str(runtime_images["postgres"])),
        "VPS_AGENT_REDIS_IMAGE": checked_image(args.redis_image or str(runtime_images["redis"])),
    }

    output_root = args.output_dir.resolve()
    bundle = output_root / f"vps-agent-{version}"
    if bundle.exists():
        raise ReleaseError(f"refusing to overwrite existing bundle: {bundle}")
    for relative in REQUIRED_BUNDLE_FILES:
        target = bundle / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(root / relative, target)

    image_values = {
        "VPS_AGENT_API_IMAGE": api,
        "VPS_AGENT_WEB_IMAGE": web,
        **base_images,
    }
    image_env = bundle / "deploy" / "release" / "images.env"
    image_env.write_text("".join(f"{key}={value}\n" for key, value in image_values.items()), encoding="ascii")
    commit_epoch = int(git_output(root, "show", "-s", "--format=%ct", commit))
    manifest = {
        "format_version": "m6.4d-release-v1",
        "version": version,
        "tag": spec["tag"],
        "commit_sha": commit,
        "schema_revision": spec["schema_revision"],
        "images": image_values,
        "created_at": datetime.fromtimestamp(commit_epoch, timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
    }
    manifest_path = bundle / "release-manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    output_root.mkdir(parents=True, exist_ok=True)
    archive = output_root / f"vps-agent-release-{version}.tar.gz"
    build_deterministic_archive(bundle, archive, output_root, commit_epoch)
    result = {
        **manifest,
        "archive": archive.name,
        "archive_sha256": sha256(archive),
    }
    (output_root / f"{archive.name}.sha256").write_text(
        f"{result['archive_sha256']}  {archive.name}\n", encoding="ascii"
    )
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    check = subparsers.add_parser("check")
    check.add_argument("--version")
    bundle = subparsers.add_parser("bundle")
    bundle.add_argument("--version", required=True)
    bundle.add_argument("--commit")
    bundle.add_argument("--api-image", required=True)
    bundle.add_argument("--web-image", required=True)
    bundle.add_argument("--caddy-image")
    bundle.add_argument("--postgres-image")
    bundle.add_argument("--redis-image")
    bundle.add_argument("--output-dir", type=Path, default=ROOT / "dist")
    args = parser.parse_args()
    try:
        result = validate_spec(ROOT, args.version) if args.command == "check" else build_bundle(args, ROOT)
    except (OSError, ReleaseError, subprocess.CalledProcessError) as error:
        print(f"release check failed: {error}", file=__import__("sys").stderr)
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
