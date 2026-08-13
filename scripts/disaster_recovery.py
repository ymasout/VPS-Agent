#!/usr/bin/env python3
"""Fail-closed encrypted disaster-recovery packaging and replica tooling."""

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
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

FORMAT_VERSION = "m6.1d-encrypted-package-v1"
AUDIT_VERSION = "m6.1d-audit-v1"
AGE_VERSION = "1.3.1"
AGE_SHA256 = {
    "linux-amd64": "bdc69c09cbdd6cf8b1f333d372a1f58247b3a33146406333e30c0f26e8f51377",
}
RECIPIENT = re.compile(r"^age1[023456789acdefghjklmnpqrstuvwxyz]{58}$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
INSTANCE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
PACKAGE_KINDS = {"database", "config", "secrets"}
MAX_FILES = 64
MAX_FILE_SIZE = 512 * 1024 * 1024
MAX_TOTAL_SIZE = 2 * 1024 * 1024 * 1024
AGE_TIMEOUT_SECONDS = 1800


class DisasterRecoveryError(RuntimeError):
    pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def require_regular(path: Path, *, max_size: int = MAX_FILE_SIZE) -> Path:
    if not path.is_absolute():
        raise DisasterRecoveryError("path must be absolute")
    try:
        info = path.lstat()
    except FileNotFoundError as error:
        raise DisasterRecoveryError("required file is missing") from error
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        raise DisasterRecoveryError("input must be a regular file, not a link")
    if info.st_size > max_size:
        raise DisasterRecoveryError("input file exceeds the size limit")
    return path.resolve(strict=True)


def require_safe_root(path: Path, *, must_exist: bool = True) -> Path:
    if not path.is_absolute() or path in {
        Path("/"),
        Path("/tmp"),
        Path("/var"),
        Path("/opt"),
    }:
        raise DisasterRecoveryError("target root is missing, relative, or too broad")
    if path.is_symlink():
        raise DisasterRecoveryError("target root must not be a symlink")
    if must_exist and not path.is_dir():
        raise DisasterRecoveryError("target root must already exist")
    return path.resolve(strict=must_exist)


def load_json(path: Path) -> dict[str, object]:
    require_regular(path, max_size=1024 * 1024)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise DisasterRecoveryError("JSON input is invalid") from error
    if not isinstance(value, dict):
        raise DisasterRecoveryError("JSON input must be an object")
    return value


def load_recipients(path: Path) -> tuple[list[str], str]:
    require_regular(path, max_size=16 * 1024)
    if os.name != "nt" and path.stat().st_mode & 0o022:
        raise DisasterRecoveryError("recipient file must not be group/other writable")
    lines = path.read_text(encoding="ascii").splitlines()
    if len(lines) != 2 or any(not RECIPIENT.fullmatch(line) for line in lines):
        raise DisasterRecoveryError(
            "recipient file must contain exactly two X25519 recipients"
        )
    if len(set(lines)) != 2:
        raise DisasterRecoveryError("recipients must be distinct")
    canonical = sorted(lines)
    set_id = hashlib.sha256(("\n".join(canonical) + "\n").encode()).hexdigest()
    return canonical, set_id


def age_command(binary: Path, *arguments: str) -> list[str]:
    prefix = [sys.executable, str(binary)] if binary.suffix == ".py" else [str(binary)]
    return [*prefix, *arguments]


def validate_age(binary: Path, expected_archive_sha256: str | None = None) -> None:
    resolved = require_regular(binary, max_size=64 * 1024 * 1024)
    marker = load_json(resolved.with_name("age.verified.json"))
    if set(marker) != {"version", "archive_sha256", "binary_sha256"}:
        raise DisasterRecoveryError("age verification marker schema is invalid")
    if (
        marker["version"] != AGE_VERSION
        or marker["archive_sha256"] not in AGE_SHA256.values()
    ):
        raise DisasterRecoveryError("age verification marker is not repository-pinned")
    if marker["binary_sha256"] != sha256_file(resolved):
        raise DisasterRecoveryError(
            "age binary checksum does not match its verified install marker"
        )
    if (
        expected_archive_sha256 is not None
        and marker["archive_sha256"] != expected_archive_sha256
    ):
        raise DisasterRecoveryError("age archive checksum is not repository-pinned")
    result = subprocess.run(
        age_command(resolved, "--version"),
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )
    output = (result.stdout + result.stderr).strip()
    if result.returncode or not re.fullmatch(
        rf"(?:age )?v?{re.escape(AGE_VERSION)}", output
    ):
        raise DisasterRecoveryError(
            "age binary version does not match the pinned version"
        )


def read_policy(path: Path) -> dict[str, object]:
    policy = load_json(path)
    expected = {
        "format_version",
        "instance_id",
        "age_binary",
        "recipients_file",
        "package_root",
        "database_backup_root",
        "audit_root",
        "control_plane_version",
        "control_plane_commit_sha",
        "alembic_revision",
        "postgres_major",
        "files",
        "replicas",
    }
    if set(policy) != expected or policy.get("format_version") != "m6.1d-policy-v1":
        raise DisasterRecoveryError("disaster recovery policy schema is invalid")
    if not INSTANCE.fullmatch(str(policy.get("instance_id", ""))):
        raise DisasterRecoveryError("policy instance_id is invalid")
    if not re.fullmatch(
        r"[0-9A-Za-z][0-9A-Za-z.+-]{0,63}", str(policy.get("control_plane_version", ""))
    ):
        raise DisasterRecoveryError("policy control plane version is invalid")
    if not re.fullmatch(
        r"[0-9a-f]{40}", str(policy.get("control_plane_commit_sha", ""))
    ):
        raise DisasterRecoveryError("policy control plane commit is invalid")
    if not re.fullmatch(r"[A-Za-z0-9_]{1,32}", str(policy.get("alembic_revision", ""))):
        raise DisasterRecoveryError("policy Alembic revision is invalid")
    if policy.get("postgres_major") != 16:
        raise DisasterRecoveryError("policy PostgreSQL major must be 16")
    files = policy.get("files")
    if not isinstance(files, dict) or set(files) != {"config", "secrets"}:
        raise DisasterRecoveryError("policy file allowlist is invalid")
    for kind, entries in files.items():
        if not isinstance(entries, list) or not entries:
            raise DisasterRecoveryError(f"policy {kind} allowlist must be non-empty")
        names: set[str] = set()
        for entry in entries:
            if not isinstance(entry, dict) or set(entry) != {"name", "path"}:
                raise DisasterRecoveryError("policy allowlist entry is invalid")
            name = str(entry["name"])
            if (
                not re.fullmatch(r"[A-Za-z0-9.][A-Za-z0-9._-]{0,63}", name)
                or name in {".", ".."}
                or name in names
            ):
                raise DisasterRecoveryError(
                    "policy logical names must be safe and unique"
                )
            names.add(name)
            if not Path(str(entry["path"])).is_absolute():
                raise DisasterRecoveryError("policy source paths must be absolute")
    replicas = policy.get("replicas")
    if not isinstance(replicas, list) or len(replicas) != 2:
        raise DisasterRecoveryError("policy must define exactly two replica targets")
    domains: set[str] = set()
    roots: set[Path] = set()
    for replica in replicas:
        if not isinstance(replica, dict) or set(replica) != {"failure_domain", "root"}:
            raise DisasterRecoveryError("replica target schema is invalid")
        domain = str(replica["failure_domain"])
        root = require_safe_root(Path(str(replica["root"])))
        if not INSTANCE.fullmatch(domain) or domain in domains or root in roots:
            raise DisasterRecoveryError(
                "replica targets or failure domains must be distinct"
            )
        domains.add(domain)
        roots.add(root)
    return policy


def record_audit(policy: dict[str, object], result: dict[str, object]) -> None:
    root = require_safe_root(Path(str(policy["audit_root"])))
    allowed = {
        "format_version",
        "action",
        "package_id",
        "kind",
        "success",
        "decryption_performed",
        "replicas",
        "warnings",
        "current_sources_match",
        "error_code",
    }
    sanitized = {key: value for key, value in result.items() if key in allowed}
    sanitized["recorded_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    atomic_json(root / f"audit-{timestamp}-{os.getpid()}.json", sanitized)


def collect_sources(
    policy: dict[str, object], kind: str, database_package: Path | None
) -> list[tuple[str, Path]]:
    if kind == "database":
        if database_package is None:
            raise DisasterRecoveryError("database package is required")
        root = require_safe_root(Path(str(policy["database_backup_root"])))
        package = require_safe_root(database_package)
        if package.parent.resolve() != root:
            raise DisasterRecoveryError(
                "database package is outside the fixed backup root"
            )
        names = {item.name for item in package.iterdir()}
        if names != {"postgres.dump", "manifest.json", "SHA256SUMS"}:
            raise DisasterRecoveryError("database package file set is invalid")
        return [
            (f"database/{name}", require_regular(package / name))
            for name in sorted(names)
        ]
    if database_package is not None:
        raise DisasterRecoveryError(
            "database package is only valid for database backups"
        )
    files = policy["files"]
    assert isinstance(files, dict)
    entries = files[kind]
    assert isinstance(entries, list)
    return [
        (f"{kind}/{entry['name']}", require_regular(Path(str(entry["path"]))))
        for entry in entries
    ]


def write_tar(sources: list[tuple[str, Path]], destination: Path) -> None:
    if len(sources) > MAX_FILES:
        raise DisasterRecoveryError("package contains too many files")
    total = sum(path.stat().st_size for _, path in sources)
    if total > MAX_TOTAL_SIZE:
        raise DisasterRecoveryError("package exceeds the total size limit")
    descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with (
        os.fdopen(descriptor, "wb") as output,
        tarfile.open(fileobj=output, mode="w") as archive,
    ):
        for name, path in sorted(sources):
            info = tarfile.TarInfo(name)
            info.size = path.stat().st_size
            info.mode = 0o600
            info.uid = info.gid = 0
            info.uname = info.gname = "root"
            info.mtime = 0
            with path.open("rb") as source:
                archive.addfile(info, source)


def atomic_json(path: Path, value: object, mode: int = 0o600) -> None:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.partial")
    temporary.write_text(
        json.dumps(value, sort_keys=True, indent=2) + "\n", encoding="utf-8"
    )
    os.chmod(temporary, mode)
    os.replace(temporary, path)


def create_package(
    policy_path: Path, kind: str, database_package: Path | None
) -> dict[str, object]:
    if kind not in PACKAGE_KINDS:
        raise DisasterRecoveryError("package kind is invalid")
    policy = read_policy(policy_path)
    age_binary = Path(str(policy["age_binary"]))
    validate_age(age_binary)
    recipients, recipient_set_id = load_recipients(Path(str(policy["recipients_file"])))
    root = require_safe_root(Path(str(policy["package_root"])))
    sources = collect_sources(policy, kind, database_package)
    created = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    package_id = f"{kind}-{created}-{os.getpid()}"
    temporary = Path(tempfile.mkdtemp(prefix=".dr-package-", dir=root))
    os.chmod(temporary, 0o700)
    plain = temporary / "payload.tar"
    try:
        write_tar(sources, plain)
        cipher = temporary / "payload.tar.age"
        command = age_command(age_binary)
        for recipient in recipients:
            command.extend(["-r", recipient])
        command.extend(["-o", str(cipher), str(plain)])
        previous_umask = os.umask(0o077)
        try:
            result = subprocess.run(
                command, capture_output=True, timeout=AGE_TIMEOUT_SECONDS, check=False
            )
        finally:
            os.umask(previous_umask)
        if result.returncode:
            raise DisasterRecoveryError("age encryption failed")
        plain.unlink()
        os.chmod(cipher, 0o600)
        manifest = {
            "format_version": FORMAT_VERSION,
            "package_id": package_id,
            "kind": kind,
            "instance_id": policy["instance_id"],
            "control_plane_version": policy["control_plane_version"],
            "control_plane_commit_sha": policy["control_plane_commit_sha"],
            "alembic_revision": policy["alembic_revision"],
            "postgres_major": policy["postgres_major"],
            "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "age_version": AGE_VERSION,
            "recipient_set_id": recipient_set_id,
            "ciphertext": {
                "name": cipher.name,
                "size_bytes": cipher.stat().st_size,
                "sha256": sha256_file(cipher),
            },
            "entries": [
                {"name": name, "size_bytes": path.stat().st_size}
                for name, path in sorted(sources)
            ],
        }
        atomic_json(temporary / "manifest.json", manifest)
        checksums = temporary / "SHA256SUMS"
        checksums.write_text(
            f"{sha256_file(cipher)}  payload.tar.age\n{sha256_file(temporary / 'manifest.json')}  manifest.json\n",
            encoding="ascii",
        )
        os.chmod(checksums, 0o600)
        final = root / package_id
        if final.exists() or final.is_symlink():
            raise DisasterRecoveryError("package destination already exists")
        os.replace(temporary, final)
        return {
            "format_version": AUDIT_VERSION,
            "action": "create",
            "package_id": package_id,
            "kind": kind,
            "success": True,
            "path": str(final),
        }
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)


def validate_package(
    package: Path, *, require_directory_name: bool = True
) -> dict[str, object]:
    package = require_safe_root(package)
    if {item.name for item in package.iterdir()} != {
        "payload.tar.age",
        "manifest.json",
        "SHA256SUMS",
    }:
        raise DisasterRecoveryError("encrypted package file set is invalid")
    for name in ("payload.tar.age", "manifest.json", "SHA256SUMS"):
        require_regular(package / name)
    manifest = load_json(package / "manifest.json")
    expected = {
        "format_version",
        "package_id",
        "kind",
        "instance_id",
        "created_at",
        "control_plane_version",
        "control_plane_commit_sha",
        "alembic_revision",
        "postgres_major",
        "age_version",
        "recipient_set_id",
        "ciphertext",
        "entries",
    }
    if (
        set(manifest) != expected
        or manifest["format_version"] != FORMAT_VERSION
        or manifest["age_version"] != AGE_VERSION
    ):
        raise DisasterRecoveryError("encrypted package manifest schema is invalid")
    if manifest["kind"] not in PACKAGE_KINDS or (
        require_directory_name and manifest["package_id"] != package.name
    ):
        raise DisasterRecoveryError("encrypted package coordinates are invalid")
    kind = str(manifest["kind"])
    if (
        not re.fullmatch(rf"{kind}-\d{{8}}T\d{{6}}Z-\d+", str(manifest["package_id"]))
        or not INSTANCE.fullmatch(str(manifest["instance_id"]))
        or not re.fullmatch(
            r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", str(manifest["created_at"])
        )
        or not re.fullmatch(
            r"[0-9A-Za-z][0-9A-Za-z.+-]{0,63}", str(manifest["control_plane_version"])
        )
        or not SHA256.fullmatch(str(manifest["recipient_set_id"]))
    ):
        raise DisasterRecoveryError("encrypted package identity metadata is invalid")
    if (
        not re.fullmatch(r"[0-9a-f]{40}", str(manifest["control_plane_commit_sha"]))
        or not re.fullmatch(r"[A-Za-z0-9_]{1,32}", str(manifest["alembic_revision"]))
        or manifest["postgres_major"] != 16
    ):
        raise DisasterRecoveryError(
            "encrypted package compatibility metadata is invalid"
        )
    ciphertext = manifest["ciphertext"]
    if (
        not isinstance(ciphertext, dict)
        or set(ciphertext) != {"name", "size_bytes", "sha256"}
        or not isinstance(ciphertext["size_bytes"], int)
        or ciphertext["size_bytes"] < 1
        or ciphertext["size_bytes"] > MAX_FILE_SIZE
        or not SHA256.fullmatch(str(ciphertext["sha256"]))
    ):
        raise DisasterRecoveryError("ciphertext manifest is invalid")
    cipher = package / "payload.tar.age"
    if (
        ciphertext["name"] != cipher.name
        or ciphertext["size_bytes"] != cipher.stat().st_size
        or ciphertext["sha256"] != sha256_file(cipher)
    ):
        raise DisasterRecoveryError("ciphertext hash or size mismatch")
    checksum_lines = (package / "SHA256SUMS").read_text(encoding="ascii").splitlines()
    expected_lines = [
        f"{sha256_file(cipher)}  payload.tar.age",
        f"{sha256_file(package / 'manifest.json')}  manifest.json",
    ]
    if checksum_lines != expected_lines:
        raise DisasterRecoveryError("SHA256SUMS is invalid")
    return manifest


def inspect_tar(
    path: Path, manifest: dict[str, object], extract_to: Path | None = None
) -> None:
    entries = manifest.get("entries")
    if not isinstance(entries, list) or not entries or len(entries) > MAX_FILES:
        raise DisasterRecoveryError("manifest entries are invalid")
    expected: set[tuple[str, int]] = set()
    total = 0
    kind = str(manifest["kind"])
    for item in entries:
        if (
            not isinstance(item, dict)
            or set(item) != {"name", "size_bytes"}
            or not isinstance(item["size_bytes"], int)
            or item["size_bytes"] < 0
            or item["size_bytes"] > MAX_FILE_SIZE
        ):
            raise DisasterRecoveryError("manifest entries are invalid")
        name = str(item["name"])
        pure = PurePosixPath(name)
        if (
            pure.is_absolute()
            or ".." in pure.parts
            or "." in pure.parts
            or "\\" in name
            or len(pure.parts) != 2
            or pure.parts[0] != kind
        ):
            raise DisasterRecoveryError("manifest entry path is invalid")
        expected.add((name, item["size_bytes"]))
        total += item["size_bytes"]
    if total > MAX_TOTAL_SIZE:
        raise DisasterRecoveryError("manifest entries exceed the total size limit")
    if len(expected) != len(entries):
        raise DisasterRecoveryError("manifest entries are invalid or duplicated")
    if kind == "database" and {name for name, _ in expected} != {
        "database/SHA256SUMS",
        "database/manifest.json",
        "database/postgres.dump",
    }:
        raise DisasterRecoveryError("database archive entry set is invalid")
    with tarfile.open(path, "r:") as archive:
        members = archive.getmembers()
        actual: set[tuple[str, int]] = set()
        for member in members:
            pure = PurePosixPath(member.name)
            if (
                not member.isfile()
                or pure.is_absolute()
                or ".." in pure.parts
                or "." in pure.parts
                or "\\" in member.name
            ):
                raise DisasterRecoveryError(
                    "decrypted archive contains an unsafe entry"
                )
            actual.add((member.name, member.size))
        if actual != expected or len(actual) != len(members):
            raise DisasterRecoveryError("decrypted archive does not match the manifest")
        if extract_to is not None:
            for member in members:
                target = extract_to / member.name
                target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                source = archive.extractfile(member)
                if source is None:
                    raise DisasterRecoveryError(
                        "decrypted archive entry cannot be read"
                    )
                with target.open("xb") as output:
                    shutil.copyfileobj(source, output)
                os.chmod(target, 0o600)


def decrypt_verify(
    policy_path: Path, package: Path, identity: Path, output: Path | None = None
) -> dict[str, object]:
    policy = read_policy(policy_path)
    validate_age(Path(str(policy["age_binary"])))
    manifest = validate_package(package)
    identity = require_regular(identity, max_size=64 * 1024)
    if os.name != "nt" and identity.stat().st_mode & 0o077:
        raise DisasterRecoveryError("identity file permissions must be 0600")
    if manifest["instance_id"] != policy["instance_id"]:
        raise DisasterRecoveryError("package instance does not match policy")
    _, recipient_set_id = load_recipients(Path(str(policy["recipients_file"])))
    if manifest["recipient_set_id"] != recipient_set_id:
        raise DisasterRecoveryError("package recipient set does not match policy")
    for field in (
        "control_plane_version",
        "control_plane_commit_sha",
        "alembic_revision",
        "postgres_major",
    ):
        if manifest[field] != policy[field]:
            raise DisasterRecoveryError(f"package {field} does not match policy")
    temporary = Path(tempfile.mkdtemp(prefix="vps-agent-dr-"))
    os.chmod(temporary, 0o700)
    plain = temporary / "payload.tar"
    try:
        previous_umask = os.umask(0o077)
        try:
            result = subprocess.run(
                age_command(
                    Path(str(policy["age_binary"])),
                    "-d",
                    "-i",
                    str(identity),
                    "-o",
                    str(plain),
                    str(package / "payload.tar.age"),
                ),
                capture_output=True,
                timeout=AGE_TIMEOUT_SECONDS,
                check=False,
            )
        finally:
            os.umask(previous_umask)
        if result.returncode:
            raise DisasterRecoveryError("age decryption failed")
        if output is not None:
            output = require_safe_root(output)
            if any(output.iterdir()):
                raise DisasterRecoveryError("decryption output directory must be empty")
        inspect_tar(plain, manifest, output)
        return {
            "format_version": AUDIT_VERSION,
            "action": "decrypt-verify",
            "package_id": manifest["package_id"],
            "kind": manifest["kind"],
            "success": True,
            "decryption_performed": True,
        }
    finally:
        shutil.rmtree(temporary, ignore_errors=True)


def verify_current_sources(
    policy_path: Path, kind: str, extracted_root: Path
) -> dict[str, object]:
    if kind not in {"config", "secrets"}:
        raise DisasterRecoveryError(
            "current-source verification only supports config or secrets"
        )
    policy = read_policy(policy_path)
    root = require_safe_root(extracted_root)
    sources = collect_sources(policy, kind, None)
    expected_names = {name for name, _ in sources}
    actual_names = {
        item.relative_to(root).as_posix()
        for item in root.rglob("*")
        if item.is_file() or item.is_symlink()
    }
    if actual_names != expected_names:
        raise DisasterRecoveryError(
            "restored current-source file set does not match policy"
        )
    for name, source in sources:
        restored = require_regular(root / name)
        if source.stat().st_size != restored.stat().st_size or sha256_file(
            source
        ) != sha256_file(restored):
            raise DisasterRecoveryError(
                "restored current-source content does not match policy"
            )
    return {
        "format_version": AUDIT_VERSION,
        "action": "verify-current",
        "kind": kind,
        "success": True,
        "current_sources_match": True,
    }


def replica_warnings(policy: dict[str, object]) -> list[str]:
    replicas = policy["replicas"]
    assert isinstance(replicas, list)
    devices = {
        require_safe_root(Path(str(replica["root"]))).stat().st_dev
        for replica in replicas
        if isinstance(replica, dict)
    }
    return ["replica_targets_share_device"] if len(devices) != len(replicas) else []


def replicate(policy_path: Path, package: Path) -> dict[str, object]:
    policy = read_policy(policy_path)
    manifest = validate_package(package)
    results = []
    replicas = policy["replicas"]
    assert isinstance(replicas, list)
    for replica in replicas:
        assert isinstance(replica, dict)
        root = require_safe_root(Path(str(replica["root"])))
        temporary = Path(tempfile.mkdtemp(prefix=".dr-replica-", dir=root))
        os.chmod(temporary, 0o700)
        try:
            for name in ("payload.tar.age", "manifest.json", "SHA256SUMS"):
                shutil.copyfile(package / name, temporary / name)
                os.chmod(temporary / name, 0o600)
            validate_package(temporary, require_directory_name=False)
            final = root / str(manifest["package_id"])
            if final.exists() or final.is_symlink():
                raise DisasterRecoveryError("refusing to replace an existing replica")
            os.replace(temporary, final)
            results.append(
                {"failure_domain": replica["failure_domain"], "sha256_verified": True}
            )
        finally:
            if temporary.exists():
                shutil.rmtree(temporary)
    return {
        "format_version": AUDIT_VERSION,
        "action": "replicate",
        "package_id": manifest["package_id"],
        "success": True,
        "replicas": results,
        "warnings": replica_warnings(policy),
    }


def audit_error_code(error: BaseException) -> str:
    if isinstance(error, DisasterRecoveryError):
        slug = re.sub(r"[^a-z0-9]+", "_", str(error).lower()).strip("_")
        return f"dr_{slug[:96]}"
    if isinstance(error, OSError):
        return f"os_error_{error.errno if error.errno is not None else 'unknown'}"
    if isinstance(error, subprocess.TimeoutExpired):
        return "subprocess_timeout"
    if isinstance(error, tarfile.TarError):
        return "archive_error"
    if isinstance(error, ValueError):
        return "value_error"
    return "unexpected_error"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--policy", type=Path, required=True)
    commands = parser.add_subparsers(dest="command", required=True)
    create = commands.add_parser("create")
    create.add_argument("--kind", choices=sorted(PACKAGE_KINDS), required=True)
    create.add_argument("--database-package", type=Path)
    verify = commands.add_parser("decrypt-verify")
    verify.add_argument("--package", type=Path, required=True)
    verify.add_argument("--identity", type=Path, required=True)
    verify.add_argument("--output", type=Path)
    copy = commands.add_parser("replicate")
    copy.add_argument("--package", type=Path, required=True)
    current = commands.add_parser("verify-current")
    current.add_argument("--kind", choices=("config", "secrets"), required=True)
    current.add_argument("--extracted-root", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.command == "create":
            result = create_package(args.policy, args.kind, args.database_package)
        elif args.command == "decrypt-verify":
            result = decrypt_verify(
                args.policy, args.package, args.identity, args.output
            )
        elif args.command == "replicate":
            result = replicate(args.policy, args.package)
        else:
            result = verify_current_sources(args.policy, args.kind, args.extracted_root)
        record_audit(read_policy(args.policy), result)
        print(json.dumps(result, sort_keys=True))
        return 0
    except (
        OSError,
        ValueError,
        subprocess.SubprocessError,
        tarfile.TarError,
        DisasterRecoveryError,
    ) as error:
        failure = {
            "format_version": AUDIT_VERSION,
            "success": False,
            "error_code": audit_error_code(error),
        }
        try:
            record_audit(read_policy(args.policy), failure)
        except Exception:
            pass
        print(json.dumps(failure, sort_keys=True), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
