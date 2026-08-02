#!/usr/bin/env python3
"""Fail-closed file transaction helper for VPS Agent upgrades."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path

SEMVER = re.compile(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")
SHA = re.compile(r"^[0-9a-f]{40}$")
UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")
REPOSITORY = "github.com/ymasout/VPS-Agent"
METADATA_FIELDS = {
    "format_version",
    "repository",
    "target_version",
    "target_tag",
    "commit_sha",
    "upgrade_from",
}
MAX_SIZES = {"binary": 128 * 1024 * 1024, "env": 1024 * 1024, "unit": 256 * 1024}
PREVIOUS_FILES = {"binary", "env", "unit", "manifest.json"}


class UpgradeError(RuntimeError):
    pass


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def fsync_directory(path: Path) -> None:
    if os.name != "posix":
        return
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def atomic_json(path: Path, value: dict[str, object], mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(value, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, mode)
        os.replace(temporary, path)
        fsync_directory(path.parent)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def atomic_copy(source: Path, destination: Path, mode: int) -> None:
    if source.is_symlink() or not source.is_file():
        raise UpgradeError(f"source must be a regular non-symlink file: {source}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{destination.name}-", dir=destination.parent)
    try:
        with source.open("rb") as reader, os.fdopen(descriptor, "wb") as writer:
            shutil.copyfileobj(reader, writer)
            writer.flush()
            os.fsync(writer.fileno())
        os.chmod(temporary, mode)
        os.replace(temporary, destination)
        fsync_directory(destination.parent)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def validate_metadata(path: Path, current: str, target: str) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise UpgradeError(f"invalid Agent upgrade metadata: {error}") from error
    if not isinstance(value, dict) or set(value) != METADATA_FIELDS:
        raise UpgradeError("Agent upgrade metadata has an invalid strict schema")
    upgrade_from = value.get("upgrade_from")
    if (
        value.get("format_version") != "vps-agent-upgrade-v1"
        or value.get("repository") != REPOSITORY
        or value.get("target_version") != target
        or value.get("target_tag") != f"v{target}"
        or not SHA.fullmatch(str(value.get("commit_sha", "")))
        or not isinstance(upgrade_from, list)
        or any(not isinstance(item, str) or not SEMVER.fullmatch(item) for item in upgrade_from)
        or len(upgrade_from) != len(set(upgrade_from))
        or upgrade_from != sorted(upgrade_from, key=lambda item: tuple(int(part) for part in item.split(".")))
        or target in upgrade_from
    ):
        raise UpgradeError("Agent upgrade metadata coordinates are invalid")
    if current not in upgrade_from:
        raise UpgradeError(f"Agent upgrade path {current} -> {target} is not supported")
    return value


def safe_state_dir(path: Path) -> Path:
    if path.exists() and path.is_symlink():
        raise UpgradeError("upgrade state directory must not be a symlink")
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(path, 0o700)
    resolved = path.resolve(strict=True)
    details = resolved.stat()
    current_uid = os.geteuid() if hasattr(os, "geteuid") else details.st_uid
    if details.st_uid != current_uid or (os.name == "posix" and details.st_mode & 0o077):
        raise UpgradeError("upgrade state directory has an unsafe owner or mode")
    return resolved


def checked_file(path: Path, kind: str) -> None:
    if path.is_symlink() or not path.is_file():
        raise UpgradeError(f"{kind} must be a regular non-symlink file")
    if path.stat().st_size > MAX_SIZES[kind]:
        raise UpgradeError(f"{kind} exceeds the size limit")


def validate_previous(previous: Path, expected_version: str | None = None) -> None:
    if previous.is_symlink() or not previous.is_dir():
        raise UpgradeError("previous generation directory is invalid")
    children = list(previous.iterdir())
    if {path.name for path in children} != PREVIOUS_FILES or any(path.is_symlink() for path in children):
        raise UpgradeError("previous generation contains unexpected files")
    try:
        manifest = json.loads((previous / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise UpgradeError(f"previous generation manifest is invalid: {error}") from error
    if (
        not isinstance(manifest, dict)
        or set(manifest) != {"format_version", "current_version", "files"}
        or manifest.get("format_version") != "vps-agent-previous-v1"
        or not isinstance(manifest.get("current_version"), str)
        or not SEMVER.fullmatch(manifest["current_version"])
        or (expected_version is not None and manifest.get("current_version") != expected_version)
        or not isinstance(manifest.get("files"), dict)
        or set(manifest["files"]) != set(MAX_SIZES)
    ):
        raise UpgradeError("previous generation manifest schema is invalid")
    for kind in MAX_SIZES:
        checked_file(previous / kind, kind)
        entry = manifest["files"][kind]
        if (
            not isinstance(entry, dict)
            or set(entry) != {"sha256", "size"}
            or entry.get("sha256") != digest(previous / kind)
            or entry.get("size") != (previous / kind).stat().st_size
        ):
            raise UpgradeError(f"previous generation {kind} integrity check failed")


def remove_managed_previous(path: Path, state: Path) -> None:
    if path.is_symlink() or not path.is_dir() or path.resolve().parent != state:
        raise UpgradeError("managed previous generation path is unsafe")
    if {child.name for child in path.iterdir()} != PREVIOUS_FILES or any(
        child.is_symlink() for child in path.iterdir()
    ):
        raise UpgradeError("managed previous generation contains unexpected files")
    shutil.rmtree(path)


def cleanup_commit_artifacts(state: Path) -> None:
    previous = state / "previous"
    replacement = state / ".previous-next"
    old_previous = state / ".previous-old"
    if replacement.exists() or replacement.is_symlink():
        validate_previous(replacement)
        remove_managed_previous(replacement, state)
    if old_previous.exists() or old_previous.is_symlink():
        validate_previous(old_previous)
        if previous.exists() or previous.is_symlink():
            validate_previous(previous)
            remove_managed_previous(old_previous, state)
        else:
            os.replace(old_previous, previous)
            fsync_directory(state)


def cleanup_stale_transactions(state: Path) -> None:
    transactions = state / "transactions"
    if not transactions.exists():
        return
    if transactions.is_symlink() or not transactions.is_dir():
        raise UpgradeError("managed transactions path is unsafe")
    for transaction in transactions.iterdir():
        if transaction.is_symlink() or not transaction.is_dir() or not UUID.fullmatch(transaction.name):
            raise UpgradeError("managed transactions path contains unexpected entries")
        if {child.name for child in transaction.iterdir()} != {"previous"}:
            raise UpgradeError("stale transaction contains unexpected files")
        validate_previous(transaction / "previous")
        shutil.rmtree(transaction)
    fsync_directory(transactions)


def load_journal(state: Path) -> dict[str, object] | None:
    path = state / "transaction.json"
    if not path.exists():
        return None
    if path.is_symlink() or not path.is_file():
        raise UpgradeError("transaction journal is not a regular file")
    value = json.loads(path.read_text(encoding="utf-8"))
    required = {
        "format_version",
        "transaction_id",
        "phase",
        "boot_id",
        "current_version",
        "target_version",
        "transaction_dir",
        "destinations",
    }
    if not isinstance(value, dict) or set(value) != required:
        raise UpgradeError("transaction journal schema is invalid")
    transaction_id = value.get("transaction_id")
    if (
        value.get("format_version") != "vps-agent-upgrade-transaction-v1"
        or not isinstance(transaction_id, str)
        or not UUID.fullmatch(transaction_id)
        or value.get("phase") != "pending_activation"
        or not isinstance(value.get("boot_id"), str)
        or not UUID.fullmatch(value["boot_id"])
        or not isinstance(value.get("current_version"), str)
        or not SEMVER.fullmatch(value["current_version"])
        or not isinstance(value.get("target_version"), str)
        or not SEMVER.fullmatch(value["target_version"])
    ):
        raise UpgradeError("transaction journal coordinates are invalid")
    transactions = state / "transactions"
    unresolved_transaction = transactions / transaction_id
    if transactions.is_symlink() or unresolved_transaction.is_symlink():
        raise UpgradeError("transaction directory must not be a symlink")
    transaction_dir = unresolved_transaction.resolve(strict=True)
    if transaction_dir.parent != transactions.resolve(strict=True):
        raise UpgradeError("transaction directory escaped the managed state")
    if str(transaction_dir) != value.get("transaction_dir"):
        raise UpgradeError("transaction directory does not match the journal")
    if {child.name for child in transaction_dir.iterdir()} != {"previous"}:
        raise UpgradeError("transaction directory contains unexpected files")
    return value


def prepare(args: argparse.Namespace) -> dict[str, object]:
    state = safe_state_dir(args.state_dir)
    if load_journal(state) is not None:
        raise UpgradeError("an interrupted Agent upgrade must be recovered first")
    cleanup_commit_artifacts(state)
    cleanup_stale_transactions(state)
    if not SEMVER.fullmatch(args.current_version) or not SEMVER.fullmatch(args.target_version):
        raise UpgradeError("transaction versions must be canonical SemVer")
    if not UUID.fullmatch(args.boot_id):
        raise UpgradeError("boot ID must be a canonical UUIDv4")
    sources = {"binary": args.candidate_binary, "env": args.candidate_env, "unit": args.candidate_unit}
    destinations = {"binary": args.binary, "env": args.env, "unit": args.unit}
    modes = {"binary": 0o755, "env": 0o600, "unit": 0o644}
    for collection in (sources, destinations):
        for kind, path in collection.items():
            checked_file(path, kind)
    required = sum(path.stat().st_size for path in [*sources.values(), *destinations.values()]) + 64 * 1024 * 1024
    if shutil.disk_usage(state).free < required:
        raise UpgradeError("insufficient free space for candidate and previous generation")
    if not UUID.fullmatch(args.transaction_id):
        raise UpgradeError("transaction ID must be a canonical UUIDv4")
    transactions = state / "transactions"
    if transactions.exists() and (transactions.is_symlink() or not transactions.is_dir()):
        raise UpgradeError("managed transactions path is unsafe")
    transactions.mkdir(mode=0o700, exist_ok=True)
    os.chmod(transactions, 0o700)
    transaction = transactions / args.transaction_id
    if transaction.exists() or transaction.is_symlink():
        raise UpgradeError("transaction directory already exists")
    previous = transaction / "previous"
    previous.mkdir(parents=True, mode=0o700)
    for kind, source in destinations.items():
        atomic_copy(source, previous / kind, modes[kind])
    manifest = {
        "format_version": "vps-agent-previous-v1",
        "current_version": args.current_version,
        "files": {kind: {"sha256": digest(previous / kind), "size": (previous / kind).stat().st_size} for kind in modes},
    }
    atomic_json(previous / "manifest.json", manifest)
    journal = {
        "format_version": "vps-agent-upgrade-transaction-v1",
        "transaction_id": args.transaction_id,
        "phase": "pending_activation",
        "boot_id": args.boot_id,
        "current_version": args.current_version,
        "target_version": args.target_version,
        "transaction_dir": str(transaction.resolve(strict=True)),
        "destinations": {kind: str(path.resolve(strict=True)) for kind, path in destinations.items()},
    }
    atomic_json(state / "transaction.json", journal)
    for kind, source in sources.items():
        atomic_copy(source, destinations[kind], modes[kind])
    return {"audit_code": "upgrade_prepared", "transaction_id": args.transaction_id}


def rollback(state_dir: Path) -> dict[str, object]:
    state = safe_state_dir(state_dir)
    journal = load_journal(state)
    if journal is None:
        return {"audit_code": "no_pending_transaction", "rolled_back": False}
    transaction = Path(str(journal["transaction_dir"]))
    previous = transaction / "previous"
    validate_previous(previous, str(journal["current_version"]))
    modes = {"binary": 0o755, "env": 0o600, "unit": 0o644}
    destinations = journal["destinations"]
    if not isinstance(destinations, dict) or set(destinations) != set(modes):
        raise UpgradeError("journal destinations are invalid")
    for kind, mode in modes.items():
        source = previous / kind
        checked_file(source, kind)
        atomic_copy(source, Path(str(destinations[kind])), mode)
    cleanup_commit_artifacts(state)
    (state / "transaction.json").unlink()
    fsync_directory(state)
    shutil.rmtree(transaction)
    return {
        "audit_code": "previous_generation_restored",
        "rolled_back": True,
        "transaction_id": journal["transaction_id"],
    }


def commit(state_dir: Path) -> dict[str, object]:
    state = safe_state_dir(state_dir)
    journal = load_journal(state)
    if journal is None:
        raise UpgradeError("there is no pending transaction to commit")
    transaction = Path(str(journal["transaction_dir"]))
    previous_source = transaction / "previous"
    validate_previous(previous_source, str(journal["current_version"]))
    previous = state / "previous"
    replacement = state / ".previous-next"
    old_previous = state / ".previous-old"
    for temporary in (replacement, old_previous):
        if temporary.exists() or temporary.is_symlink():
            raise UpgradeError("previous generation temporary path already exists")
    if previous.exists() or previous.is_symlink():
        validate_previous(previous)
    replacement.mkdir(mode=0o700)
    for kind, mode in {"binary": 0o755, "env": 0o600, "unit": 0o644}.items():
        atomic_copy(previous_source / kind, replacement / kind, mode)
    previous_manifest = json.loads((previous_source / "manifest.json").read_text(encoding="utf-8"))
    atomic_json(replacement / "manifest.json", previous_manifest)
    validate_previous(replacement, str(journal["current_version"]))
    fsync_directory(state)
    if previous.exists():
        os.replace(previous, old_previous)
    os.replace(replacement, previous)
    fsync_directory(state)
    # Removing the journal is the commit point. Before it, recovery can still
    # restore the transaction-local previous generation after any interruption.
    (state / "transaction.json").unlink()
    fsync_directory(state)
    shutil.rmtree(transaction)
    cleanup_commit_artifacts(state)
    return {
        "audit_code": "upgrade_committed",
        "transaction_id": journal["transaction_id"],
        "target_version": journal["target_version"],
    }


def recover_if_new_boot(state_dir: Path, boot_id: str) -> dict[str, object]:
    if not UUID.fullmatch(boot_id):
        raise UpgradeError("boot ID must be a canonical UUIDv4")
    state = safe_state_dir(state_dir)
    journal = load_journal(state)
    if journal is None or journal.get("boot_id") == boot_id:
        return {"audit_code": "boot_recovery_not_required", "rolled_back": False}
    return rollback(state)


def add_transaction_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--state-dir", type=Path, required=True)
    parser.add_argument("--candidate-binary", type=Path, required=True)
    parser.add_argument("--candidate-env", type=Path, required=True)
    parser.add_argument("--candidate-unit", type=Path, required=True)
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--env", type=Path, required=True)
    parser.add_argument("--unit", type=Path, required=True)
    parser.add_argument("--current-version", required=True)
    parser.add_argument("--target-version", required=True)
    parser.add_argument("--boot-id", required=True)
    parser.add_argument("--transaction-id", required=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    metadata = subparsers.add_parser("validate-metadata")
    metadata.add_argument("--metadata", type=Path, required=True)
    metadata.add_argument("--current", required=True)
    metadata.add_argument("--target", required=True)
    prepare_parser = subparsers.add_parser("prepare")
    add_transaction_args(prepare_parser)
    for name in ("commit", "rollback"):
        value = subparsers.add_parser(name)
        value.add_argument("--state-dir", type=Path, required=True)
    recover = subparsers.add_parser("recover-if-new-boot")
    recover.add_argument("--state-dir", type=Path, required=True)
    recover.add_argument("--boot-id", required=True)
    args = parser.parse_args()
    try:
        if args.command == "validate-metadata":
            result = validate_metadata(args.metadata, args.current, args.target)
        elif args.command == "prepare":
            result = prepare(args)
        elif args.command == "commit":
            result = commit(args.state_dir)
        elif args.command == "rollback":
            result = rollback(args.state_dir)
        else:
            result = recover_if_new_boot(args.state_dir, args.boot_id)
    except (OSError, json.JSONDecodeError, UpgradeError) as error:
        print(json.dumps({"audit_code": "upgrade_helper_failed", "error": str(error)}, sort_keys=True), file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
