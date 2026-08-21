import hashlib
import importlib.util
import io
import json
import os
import stat
import tarfile
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "disaster_recovery.py"
SPEC = importlib.util.spec_from_file_location("disaster_recovery", SCRIPT)
assert SPEC and SPEC.loader
dr = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(dr)


def make_executable(path: Path) -> Path:
    path = path.with_suffix(".py")
    path.write_text(
        """#!/usr/bin/env python3
import shutil, sys
if sys.argv[1:] == ['--version']:
    print('1.3.1'); raise SystemExit(0)
if '-d' in sys.argv:
    identity = sys.argv[sys.argv.index('-i') + 1]
    if open(identity, encoding='utf-8').read().strip() == 'wrong':
        raise SystemExit(1)
    output = sys.argv[sys.argv.index('-o') + 1]
    shutil.copyfile(sys.argv[-1], output); raise SystemExit(0)
output = sys.argv[sys.argv.index('-o') + 1]
shutil.copyfile(sys.argv[-1], output)
""",
        encoding="utf-8",
    )
    path.chmod(0o755)
    marker = {
        "version": "1.3.1",
        "archive_sha256": dr.AGE_SHA256["linux-amd64"],
        "binary_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }
    path.with_name("age.verified.json").write_text(json.dumps(marker), encoding="utf-8")
    return path


def fixture(tmp_path: Path) -> tuple[Path, dict]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    roots = {
        name: tmp_path / name
        for name in ("packages", "database", "audit", "replica-a", "replica-b")
    }
    for root in roots.values():
        root.mkdir()
    age = make_executable(tmp_path / "age")
    recipients = tmp_path / "recipients.txt"
    recipients.write_text("age1" + "q" * 58 + "\n" + "age1" + "p" * 58 + "\n", encoding="ascii")
    recipients.chmod(0o644)
    config = tmp_path / "compose.yaml"
    secret = tmp_path / ".env.production"
    config.write_text("services: {}\n", encoding="utf-8")
    secret.write_text("ADMIN_API_TOKEN=test-secret\n", encoding="utf-8")
    policy = {
        "format_version": "m6.1d-policy-v1",
        "instance_id": "test-instance",
        "age_binary": str(age.resolve()),
        "recipients_file": str(recipients.resolve()),
        "package_root": str(roots["packages"].resolve()),
        "database_backup_root": str(roots["database"].resolve()),
        "audit_root": str(roots["audit"].resolve()),
        "control_plane_version": "0.6.5",
        "control_plane_commit_sha": "a" * 40,
        "alembic_revision": "0020_m6_named_approval",
        "postgres_major": 16,
        "files": {
            "config": [{"name": "compose.yaml", "path": str(config.resolve())}],
            "secrets": [{"name": ".env.production", "path": str(secret.resolve())}],
        },
        "replicas": [
            {"failure_domain": "site-a", "root": str(roots["replica-a"].resolve())},
            {"failure_domain": "site-b", "root": str(roots["replica-b"].resolve())},
        ],
    }
    policy_path = tmp_path / "policy.json"
    policy_path.write_text(json.dumps(policy), encoding="utf-8")
    return policy_path, policy


def identity(tmp_path: Path, value: str = "valid") -> Path:
    result = tmp_path / f"identity-{value}.txt"
    result.write_text(value, encoding="utf-8")
    result.chmod(0o600)
    return result


@pytest.mark.parametrize("kind", ["config", "secrets"])
def test_encrypted_packages_round_trip_and_cleanup(
    kind: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(dr.tempfile, "tempdir", str(tmp_path))
    policy_path, _ = fixture(tmp_path)
    created = dr.create_package(policy_path, kind, None)
    package = Path(created["path"])
    output = tmp_path / "output"
    output.mkdir()
    result = dr.decrypt_verify(policy_path, package, identity(tmp_path), output)
    assert result["decryption_performed"] is True
    assert (output / kind).is_dir()
    assert dr.verify_current_sources(policy_path, kind, output)["current_sources_match"] is True
    assert not list(tmp_path.glob("vps-agent-dr-*"))


def test_same_package_can_be_decrypted_by_either_offline_identity(tmp_path: Path) -> None:
    policy_path, _ = fixture(tmp_path)
    package = Path(dr.create_package(policy_path, "config", None)["path"])
    for name in ("offline-a", "offline-b"):
        assert dr.decrypt_verify(policy_path, package, identity(tmp_path, name))["success"] is True


def test_decrypt_rejects_policy_recipient_set_mismatch(tmp_path: Path) -> None:
    policy_path, policy = fixture(tmp_path)
    package = Path(dr.create_package(policy_path, "config", None)["path"])
    Path(policy["recipients_file"]).write_text(
        "age1" + "q" * 58 + "\n" + "age1" + "z" * 58 + "\n", encoding="ascii"
    )
    with pytest.raises(dr.DisasterRecoveryError, match="recipient set"):
        dr.decrypt_verify(policy_path, package, identity(tmp_path))


def test_wrong_identity_and_corrupted_ciphertext_fail_closed(tmp_path: Path) -> None:
    policy_path, _ = fixture(tmp_path)
    package = Path(dr.create_package(policy_path, "secrets", None)["path"])
    with pytest.raises(dr.DisasterRecoveryError, match="decryption failed"):
        dr.decrypt_verify(policy_path, package, identity(tmp_path, "wrong"))
    with (package / "payload.tar.age").open("ab") as output:
        output.write(b"damage")
    with pytest.raises(dr.DisasterRecoveryError, match="hash or size"):
        dr.validate_package(package)


def test_manifest_and_sha256_tampering_fail_closed(tmp_path: Path) -> None:
    policy_path, _ = fixture(tmp_path)
    package = Path(dr.create_package(policy_path, "config", None)["path"])
    manifest = json.loads((package / "manifest.json").read_text())
    manifest["unknown"] = True
    (package / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(dr.DisasterRecoveryError, match="manifest schema"):
        dr.validate_package(package)

    policy_path, _ = fixture(tmp_path / "other")
    package = Path(dr.create_package(policy_path, "config", None)["path"])
    (package / "SHA256SUMS").write_text("0" * 64 + "  payload.tar.age\n")
    with pytest.raises(dr.DisasterRecoveryError, match="SHA256SUMS"):
        dr.validate_package(package)


def test_allowlist_rejects_symlink_duplicate_and_relative_sources(tmp_path: Path) -> None:
    policy_path, policy = fixture(tmp_path)
    target = tmp_path / "real-secret"
    target.write_text("secret")
    link = tmp_path / "secret-link"
    try:
        link.symlink_to(target)
    except OSError:
        pytest.skip("symlinks unavailable")
    policy["files"]["secrets"][0]["path"] = str(link.absolute())
    policy_path.write_text(json.dumps(policy))
    with pytest.raises(dr.DisasterRecoveryError, match="regular file"):
        dr.create_package(policy_path, "secrets", None)

    policy["files"]["secrets"] = [
        {"name": "duplicate", "path": "relative"},
        {"name": "duplicate", "path": str(target.resolve())},
    ]
    policy_path.write_text(json.dumps(policy))
    with pytest.raises(dr.DisasterRecoveryError):
        dr.read_policy(policy_path)


def test_allowlist_rejects_oversized_files(tmp_path: Path) -> None:
    policy_path, policy = fixture(tmp_path)
    oversized = tmp_path / "oversized"
    with oversized.open("wb") as output:
        output.seek(dr.MAX_FILE_SIZE)
        output.write(b"x")
    policy["files"]["config"][0]["path"] = str(oversized.resolve())
    policy_path.write_text(json.dumps(policy))
    with pytest.raises(dr.DisasterRecoveryError, match="size limit"):
        dr.create_package(policy_path, "config", None)


def test_database_package_must_be_direct_child_with_exact_file_set(tmp_path: Path) -> None:
    policy_path, policy = fixture(tmp_path)
    database = Path(policy["database_backup_root"]) / "control-plane-test"
    database.mkdir()
    for name in ("postgres.dump", "manifest.json", "SHA256SUMS"):
        (database / name).write_text(name)
    result = dr.create_package(policy_path, "database", database)
    assert result["kind"] == "database"
    (database / "extra").write_text("bad")
    with pytest.raises(dr.DisasterRecoveryError, match="file set"):
        dr.create_package(policy_path, "database", database)


def test_atomic_replication_requires_two_distinct_failure_domains(tmp_path: Path) -> None:
    policy_path, policy = fixture(tmp_path)
    package = Path(dr.create_package(policy_path, "config", None)["path"])
    result = dr.replicate(policy_path, package)
    assert len(result["replicas"]) == 2
    assert all(item["sha256_verified"] for item in result["replicas"])
    assert result["warnings"] == ["replica_targets_share_device"]
    for replica in policy["replicas"]:
        assert (Path(replica["root"]) / package.name / "SHA256SUMS").is_file()

    policy["replicas"][1]["failure_domain"] = "site-a"
    policy_path.write_text(json.dumps(policy))
    with pytest.raises(dr.DisasterRecoveryError, match="distinct"):
        dr.read_policy(policy_path)


def test_age_version_is_pinned_and_unknown_path_version_is_rejected(tmp_path: Path) -> None:
    good = make_executable(tmp_path / "age")
    dr.validate_age(good)
    bad = make_executable(tmp_path / "age-bad")
    bad.write_text("#!/usr/bin/env python3\nprint('9.9.9')\n")
    marker = json.loads(bad.with_name("age.verified.json").read_text())
    marker["binary_sha256"] = hashlib.sha256(bad.read_bytes()).hexdigest()
    bad.with_name("age.verified.json").write_text(json.dumps(marker))
    with pytest.raises(dr.DisasterRecoveryError, match="pinned version"):
        dr.validate_age(bad)
    assert dr.AGE_SHA256["linux-amd64"] == (
        "bdc69c09cbdd6cf8b1f333d372a1f58247b3a33146406333e30c0f26e8f51377"
    )
    assert set(dr.AGE_SHA256) == {"linux-amd64"}


def test_plaintext_tar_and_decrypted_payload_are_mode_0600(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    if os.name == "nt":
        pytest.skip("POSIX permission modes are verified on Linux CI")
    source = tmp_path / "source"
    source.write_text("secret")
    archive = tmp_path / "payload.tar"
    dr.write_tar([("config/source", source)], archive)
    assert stat.S_IMODE(archive.stat().st_mode) == 0o600

    policy_path, _ = fixture(tmp_path / "fixture")
    package = Path(dr.create_package(policy_path, "config", None)["path"])
    original = dr.inspect_tar

    def inspect_mode(path: Path, manifest: dict, extract_to: Path | None = None) -> None:
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
        original(path, manifest, extract_to)

    monkeypatch.setattr(dr, "inspect_tar", inspect_mode)
    dr.decrypt_verify(policy_path, package, identity(tmp_path / "fixture"))


def test_current_source_verification_rejects_stale_secret(tmp_path: Path) -> None:
    policy_path, _ = fixture(tmp_path)
    package = Path(dr.create_package(policy_path, "secrets", None)["path"])
    output = tmp_path / "output"
    output.mkdir()
    dr.decrypt_verify(policy_path, package, identity(tmp_path), output)
    (output / "secrets" / ".env.production").write_text("stale=true\n")
    with pytest.raises(dr.DisasterRecoveryError, match="content does not match"):
        dr.verify_current_sources(policy_path, "secrets", output)


def test_audit_error_codes_do_not_include_paths() -> None:
    error = PermissionError(13, "Permission denied", "/secret/production.env")
    assert dr.audit_error_code(error) == "os_error_13"


@pytest.mark.parametrize("name", ["../escape", "/absolute", "safe/../escape", "safe\\escape"])
def test_decrypted_archive_rejects_path_traversal_and_absolute_paths(
    name: str, tmp_path: Path
) -> None:
    archive_path = tmp_path / "payload.tar"
    content = b"x"
    with tarfile.open(archive_path, "w") as archive:
        info = tarfile.TarInfo(name)
        info.size = len(content)
        archive.addfile(info, io.BytesIO(content))
    manifest = {"kind": "config", "entries": [{"name": name, "size_bytes": len(content)}]}
    with pytest.raises(dr.DisasterRecoveryError, match="entry path"):
        dr.inspect_tar(archive_path, manifest)


def test_decrypted_archive_rejects_links_duplicates_and_size_mismatch(tmp_path: Path) -> None:
    archive_path = tmp_path / "payload.tar"
    with tarfile.open(archive_path, "w") as archive:
        first = tarfile.TarInfo("config/file")
        first.size = 1
        archive.addfile(first, io.BytesIO(b"a"))
        duplicate = tarfile.TarInfo("config/file")
        duplicate.size = 1
        archive.addfile(duplicate, io.BytesIO(b"b"))
    manifest = {"kind": "config", "entries": [{"name": "config/file", "size_bytes": 1}]}
    with pytest.raises(dr.DisasterRecoveryError, match="does not match"):
        dr.inspect_tar(archive_path, manifest)

    with tarfile.open(archive_path, "w") as archive:
        link = tarfile.TarInfo("config/link")
        link.type = tarfile.SYMTYPE
        link.linkname = "target"
        archive.addfile(link)
    manifest = {"kind": "config", "entries": [{"name": "config/link", "size_bytes": 0}]}
    with pytest.raises(dr.DisasterRecoveryError, match="unsafe entry"):
        dr.inspect_tar(archive_path, manifest)

    with tarfile.open(archive_path, "w") as archive:
        info = tarfile.TarInfo("config/file")
        info.size = 2
        archive.addfile(info, io.BytesIO(b"ab"))
    manifest = {"kind": "config", "entries": [{"name": "config/file", "size_bytes": 1}]}
    with pytest.raises(dr.DisasterRecoveryError, match="does not match"):
        dr.inspect_tar(archive_path, manifest)


def test_decrypted_archive_rejects_oversized_manifest_entry(tmp_path: Path) -> None:
    archive_path = tmp_path / "payload.tar"
    with tarfile.open(archive_path, "w"):
        pass
    manifest = {
        "kind": "config",
        "entries": [{"name": "config/file", "size_bytes": dr.MAX_FILE_SIZE + 1}],
    }
    with pytest.raises(dr.DisasterRecoveryError, match="manifest entries"):
        dr.inspect_tar(archive_path, manifest)


def test_drill_and_timer_keep_rto_and_manual_key_boundaries() -> None:
    root = Path(__file__).resolve().parents[3]
    drill = (root / "deploy" / "control-plane-drill.sh").read_text()
    timer = (root / "deploy" / "systemd" / "vps-agent-dr-database.timer").read_text()
    service = (root / "deploy" / "systemd" / "vps-agent-dr-database.service").read_text()
    installer = (root / "deploy" / "install-disaster-recovery.sh").read_text()
    wrapper = (root / "deploy" / "control-plane-disaster-recovery.sh").read_text()
    web_dockerfile = (root / "apps" / "web" / "Dockerfile").read_text()
    assert '"rto_limit_seconds":14400' in drill
    assert '"rto_met":total <= 14400' in drill
    assert '"database_rpo_limit_seconds":86400' in drill
    assert '"change_driven_freshness_verified":True' in drill
    assert '"config_restored":True' in drill
    assert '"instance_isolated":sys.argv[6] != sys.argv[7]' in drill
    assert '"production_agent_connectivity":False' in drill
    for variable in (
        "CADDY_ADMIN_USER",
        "CADDY_ADMIN_PASSWORD_HASH",
        "CADDY_OPERATOR_USER",
        "CADDY_OPERATOR_PASSWORD_HASH",
        "CADDY_APPROVER_USER",
        "CADDY_APPROVER_PASSWORD_HASH",
    ):
        assert f'"{variable}"' in drill
    assert "isolated env POSTGRES_DB must exactly match" in drill
    assert "isolated env POSTGRES_USER must exactly match" in drill
    assert "OnCalendar=daily" in timer and "Persistent=true" in timer
    assert "ExecStart=/usr/local/libexec/vps-agent/run-database-backup" in service
    assert "install -d -o root -g root -m 0755 /usr/local/libexec/vps-agent" in installer
    assert "monthly-check ABSOLUTE_PACKAGE ABSOLUTE_OFFLINE_IDENTITY" in wrapper
    assert "HOSTNAME=0.0.0.0" in web_dockerfile


def test_isolated_compose_resets_control_plane_write_credentials() -> None:
    root = Path(__file__).resolve().parents[3]
    override = (root / "deploy" / "compose.disaster-recovery.yaml").read_text()
    for variable in (
        "OPERATION_SIGNING_PRIVATE_KEY_BASE64",
        "OPERATION_SIGNING_KEY_ID",
        "PRINCIPAL_PROXY_TOKEN",
        "PRINCIPAL_WRITE_PROXY_TOKEN",
        "PRINCIPAL_ROLE_BINDINGS_JSON",
        "PRINCIPAL_VIEWER_IDS",
    ):
        assert f"{variable}: !reset null" in override


@pytest.mark.skipif(os.name == "nt", reason="Git executable bits are POSIX-only")
def test_disaster_recovery_shell_entrypoints_are_executable() -> None:
    root = Path(__file__).resolve().parents[3]
    paths = (
        *sorted((root / "deploy").glob("control-plane-*.sh")),
        *sorted((root / "deploy").glob("install-*.sh")),
        root / "deploy" / "systemd" / "run-database-backup",
        *sorted((root / "deploy" / "tests").glob("*.sh")),
    )
    assert paths
    assert all(os.access(path, os.X_OK) for path in paths)
