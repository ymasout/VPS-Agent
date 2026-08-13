#!/usr/bin/env python3
"""Verify and safely stage a signed VPS Agent control-plane release bundle."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
from datetime import datetime
from pathlib import Path, PurePosixPath

COSIGN_IDENTITY = "https://github.com/ymasout/VPS-Agent/.github/workflows/formal-release.yml@refs/heads/main"
COSIGN_ISSUER = "https://token.actions.githubusercontent.com"
SEMVER = re.compile(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")
DIGEST = re.compile(r"^[a-z0-9.-]+(?::[0-9]+)?/[a-z0-9._/-]+@sha256:[0-9a-f]{64}$")
MAX_FILES = 256
MAX_TOTAL_BYTES = 512 * 1024 * 1024
IMAGE_KEYS = (
    "VPS_AGENT_API_IMAGE",
    "VPS_AGENT_WEB_IMAGE",
    "VPS_AGENT_CADDY_IMAGE",
    "VPS_AGENT_POSTGRES_IMAGE",
    "VPS_AGENT_REDIS_IMAGE",
)
ALLOWED_FILES = {
    "LICENSE",
    "LICENSING.md",
    "NOTICE",
    "THIRD_PARTY_NOTICES.md",
    "CHANGELOG.md",
    "release/release.json",
    "docs/RELEASE_COMPATIBILITY.md",
    "docs/RELEASE_PROCESS.md",
    "docs/M6_DISASTER_RECOVERY.md",
    "deploy/compose.production.yaml",
    "deploy/compose.disaster-recovery.yaml",
    "deploy/release/compose.release.yaml",
    "deploy/release/.env.release.example",
    "deploy/release/images.env",
    "deploy/.env.production.example",
    "deploy/caddy/Caddyfile",
    "deploy/control-plane-release.sh",
    "deploy/control-plane-backup.sh",
    "deploy/control-plane-restore.sh",
    "deploy/control-plane-disaster-recovery.sh",
    "deploy/control-plane-drill.sh",
    "deploy/install-age.sh",
    "deploy/install-disaster-recovery.sh",
    "deploy/disaster-recovery-policy.example.json",
    "deploy/backup-recipients.example.txt",
    "deploy/systemd/vps-agent-dr-database.service",
    "deploy/systemd/vps-agent-dr-database.timer",
    "deploy/systemd/run-database-backup",
    "scripts/disaster_recovery.py",
    "scripts/stage_release.py",
    "release-manifest.json",
}
ALLOWED_DIRECTORIES = {
    parent.as_posix()
    for relative in ALLOWED_FILES
    for parent in PurePosixPath(relative).parents
    if parent.as_posix() != "."
}


class StageError(RuntimeError):
    pass


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def verify_blob(path: Path, bundle: Path) -> None:
    subprocess.run(
        [
            "cosign",
            "verify-blob",
            "--bundle",
            str(bundle),
            "--certificate-identity",
            COSIGN_IDENTITY,
            "--certificate-oidc-issuer",
            COSIGN_ISSUER,
            str(path),
        ],
        check=True,
        stdout=subprocess.DEVNULL,
    )


def expected_checksum(checksum_file: Path, archive_name: str) -> str:
    lines = checksum_file.read_text(encoding="ascii").splitlines()
    matches = []
    for line in lines:
        match = re.fullmatch(r"([0-9a-f]{64})  ([A-Za-z0-9._-]+)", line)
        if not match:
            raise StageError("checksum file contains an invalid line")
        if match.group(2) == archive_name:
            matches.append(match.group(1))
    if len(matches) != 1:
        raise StageError("checksum file must contain the archive exactly once")
    return matches[0]


def validate_members(members: list[tarfile.TarInfo]) -> str:
    if len(members) > MAX_FILES:
        raise StageError("archive contains too many entries")
    normalized: set[str] = set()
    top_levels: set[str] = set()
    files: set[str] = set()
    total_bytes = 0
    for member in members:
        name = member.name
        if not name or "\x00" in name or "\\" in name:
            raise StageError("archive contains an invalid path")
        path = PurePosixPath(name)
        if path.is_absolute() or any(part in ("", ".", "..") for part in path.parts):
            raise StageError("archive path escapes or is not normalized")
        canonical = path.as_posix().rstrip("/")
        if canonical in normalized:
            raise StageError("archive contains a duplicate normalized path")
        normalized.add(canonical)
        top_levels.add(path.parts[0])
        if member.issym() or member.islnk() or member.isdev() or member.isfifo():
            raise StageError("archive links and special files are forbidden")
        if not (member.isdir() or member.isfile()):
            raise StageError("archive contains an unsupported entry type")
        if member.isfile():
            if member.size < 0:
                raise StageError("archive contains a negative file size")
            total_bytes += member.size
            files.add(PurePosixPath(*path.parts[1:]).as_posix())
        elif len(path.parts) > 1:
            relative_directory = PurePosixPath(*path.parts[1:]).as_posix()
            if relative_directory not in ALLOWED_DIRECTORIES:
                raise StageError("archive directory allowlist mismatch")
    if len(top_levels) != 1:
        raise StageError("archive must contain exactly one top-level directory")
    top = next(iter(top_levels))
    if not re.fullmatch(r"vps-agent-(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)", top):
        raise StageError("archive top-level directory is invalid")
    if total_bytes > MAX_TOTAL_BYTES:
        raise StageError("archive expanded size exceeds the limit")
    if files != ALLOWED_FILES:
        missing = sorted(ALLOWED_FILES - files)
        extra = sorted(files - ALLOWED_FILES)
        raise StageError(f"archive file allowlist mismatch; missing={missing} extra={extra}")
    return top


def parse_images_env(path: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    lines = path.read_text(encoding="ascii").splitlines()
    for line in lines:
        match = re.fullmatch(r"([A-Z][A-Z0-9_]*)=(.+)", line)
        if not match or match.group(1) in result:
            raise StageError("images.env is invalid or contains duplicate keys")
        result[match.group(1)] = match.group(2)
    if tuple(result) != IMAGE_KEYS:
        raise StageError("images.env key set or order is invalid")
    if any(not DIGEST.fullmatch(value) for value in result.values()):
        raise StageError("images.env contains a non-canonical digest")
    return result


def validate_extracted(root: Path, top: str) -> dict[str, object]:
    base = root / top
    resolved_base = base.resolve(strict=True)
    actual_files: set[str] = set()
    for path in base.rglob("*"):
        if path.is_symlink():
            raise StageError("extracted bundle contains a link")
        resolved = path.resolve(strict=True)
        if resolved != resolved_base and resolved_base not in resolved.parents:
            raise StageError("extracted path escaped the staging root")
        if path.is_file():
            actual_files.add(path.relative_to(base).as_posix())
    if actual_files != ALLOWED_FILES:
        raise StageError("extracted file allowlist does not match the archive")
    manifest = json.loads((base / "release-manifest.json").read_text(encoding="utf-8"))
    release_spec = json.loads((base / "release/release.json").read_text(encoding="utf-8"))
    expected_fields = {
        "format_version",
        "version",
        "tag",
        "commit_sha",
        "schema_revision",
        "images",
        "created_at",
    }
    if not isinstance(manifest, dict) or set(manifest) != expected_fields:
        raise StageError("release manifest schema is invalid")
    version = manifest.get("version")
    if (
        manifest.get("format_version") != "m6.4d-release-v1"
        or not isinstance(version, str)
        or not SEMVER.fullmatch(version)
        or manifest.get("tag") != f"v{version}"
        or top != f"vps-agent-{version}"
        or not re.fullmatch(r"[0-9a-f]{40}", str(manifest.get("commit_sha", "")))
        or not isinstance(manifest.get("schema_revision"), str)
        or not re.fullmatch(r"[A-Za-z0-9_]{1,32}", manifest["schema_revision"])
    ):
        raise StageError("release manifest coordinates are invalid")
    try:
        created_at = datetime.strptime(str(manifest.get("created_at")), "%Y-%m-%dT%H:%M:%SZ")
    except ValueError as error:
        raise StageError("release manifest created_at is invalid") from error
    if created_at.strftime("%Y-%m-%dT%H:%M:%SZ") != manifest["created_at"]:
        raise StageError("release manifest created_at is not canonical")
    if not isinstance(release_spec, dict) or any(
        release_spec.get(key) != manifest.get(key) for key in ("version", "tag", "schema_revision")
    ):
        raise StageError("release manifest does not match release/release.json")
    images = parse_images_env(base / "deploy/release/images.env")
    if manifest.get("images") != images:
        raise StageError("images.env does not match release-manifest.json")
    return manifest


def fsync_tree(root: Path) -> None:
    for path in sorted(root.rglob("*"), reverse=True):
        if path.is_file():
            with path.open("rb") as handle:
                os.fsync(handle.fileno())
    for path in [*sorted((item for item in root.rglob("*") if item.is_dir()), reverse=True), root]:
        descriptor = os.open(path, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


def stage(args: argparse.Namespace) -> dict[str, object]:
    if sys.version_info < (3, 12):
        raise StageError("Python 3.12 or newer is required")
    if os.name != "posix" or os.geteuid() != 0:
        raise StageError("release staging must run as root on a POSIX host")
    for path in (args.archive, args.checksum, args.archive_bundle, args.checksum_bundle):
        if not path.is_file() or path.is_symlink():
            raise StageError(f"required regular input file is missing: {path}")
    verify_blob(args.archive, args.archive_bundle)
    verify_blob(args.checksum, args.checksum_bundle)
    if sha256(args.archive) != expected_checksum(args.checksum, args.archive.name):
        raise StageError("release archive checksum mismatch")
    requested_destination = args.destination.absolute()
    for component in (requested_destination, *requested_destination.parents):
        if component.exists() and component.is_symlink():
            raise StageError("destination and its existing parents must not be symlinks")
    requested_destination.mkdir(parents=True, exist_ok=True, mode=0o700)
    destination = requested_destination.resolve(strict=True)
    destination.mkdir(parents=True, exist_ok=True, mode=0o700)
    mode = stat.S_IMODE(destination.stat().st_mode)
    if destination.stat().st_uid != 0 or mode & 0o022:
        raise StageError("destination must be root-owned and not group/other writable")
    temp = Path(tempfile.mkdtemp(prefix=".release-stage-", dir=destination))
    os.chmod(temp, 0o700)
    try:
        with tarfile.open(args.archive, mode="r:gz") as archive:
            members = archive.getmembers()
            top = validate_members(members)
            archive.extractall(temp, members=members, filter="data")
        manifest = validate_extracted(temp, top)
        staged = destination / f"{manifest['version']}-{manifest['commit_sha']}"
        if staged.exists() or staged.is_symlink():
            raise StageError("refusing to replace an existing staged release")
        for path in temp.rglob("*"):
            if path.is_file():
                os.chmod(path, 0o600)
            elif path.is_dir():
                os.chmod(path, 0o700)
        verified = {
            "format_version": "vps-agent-staged-release-v1",
            "archive_sha256": sha256(args.archive),
            "version": manifest["version"],
            "commit_sha": manifest["commit_sha"],
            "schema_revision": manifest["schema_revision"],
        }
        marker = temp / top / ".verified-release.json"
        marker.write_text(json.dumps(verified, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        os.chmod(marker, 0o600)
        fsync_tree(temp / top)
        os.replace(temp / top, staged)
        pending = destination / ".pending-release.json.tmp"
        pending.write_text(json.dumps({**verified, "staged_path": str(staged)}, sort_keys=True) + "\n", encoding="utf-8")
        os.chmod(pending, 0o600)
        with pending.open("rb") as handle:
            os.fsync(handle.fileno())
        os.replace(pending, destination / "pending-release.json")
        descriptor = os.open(destination, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        return verified
    finally:
        if temp.exists():
            shutil.rmtree(temp)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--checksum", type=Path, required=True)
    parser.add_argument("--archive-bundle", type=Path, required=True)
    parser.add_argument("--checksum-bundle", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = stage(args)
    except (OSError, json.JSONDecodeError, tarfile.TarError, subprocess.CalledProcessError, StageError) as error:
        print(f"release staging failed: {error}", file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
