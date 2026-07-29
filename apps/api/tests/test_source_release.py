import hashlib
import importlib.util
import json
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "source_release.py"
SPEC = importlib.util.spec_from_file_location("source_release", SCRIPT)
assert SPEC and SPEC.loader
source_release = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(source_release)


def test_source_release_rejects_runtime_and_sensitive_paths() -> None:
    assert source_release.validate_path(".env") == ["runtime environment file"]
    assert source_release.validate_path("deploy/.env.production") == [
        "runtime environment file"
    ]
    assert source_release.validate_path("backup/control.dump")
    assert source_release.validate_path("Backups/control.txt")
    assert source_release.validate_path("node_modules/package/index.js")
    assert source_release.validate_path("DEPLOY/.ENV.PRODUCTION")


def test_source_release_allows_only_documented_environment_examples() -> None:
    assert source_release.validate_path(".env.example") == []
    assert source_release.validate_path("deploy/.env.production.example") == []


def test_source_release_detects_realistic_secrets_but_allows_short_fake_fixtures() -> None:
    assert source_release.scan_text("fixture.py", "ghp_short-test-value") == []
    assert source_release.scan_text("secret.txt", "ghp_" + "A" * 40) == [
        "github_token"
    ]
    fake_key = "-----BEGIN PRIVATE KEY-----\nabc123\n-----END PRIVATE KEY-----"
    assert source_release.scan_text("fixture.py", fake_key) == []
    realistic_key = (
        "-----BEGIN PRIVATE KEY-----\n"
        + "A" * 256
        + "\n-----END PRIVATE KEY-----"
    )
    assert source_release.scan_text("secret.pem.txt", realistic_key) == ["private_key"]
    encrypted_key = (
        "-----BEGIN ENCRYPTED PRIVATE KEY-----\n"
        + "A" * 256
        + "\n-----END ENCRYPTED PRIVATE KEY-----"
    )
    assert source_release.scan_text("encrypted.txt", encrypted_key) == ["private_key"]


def test_source_release_builds_commit_bound_archive_and_rejects_dirty_tree(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    (repository / "README.md").write_text("safe source\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=repository, check=True)
    subprocess.run(["git", "add", "README.md"], cwd=repository, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Source Test",
            "-c",
            "user.email=source-test@example.invalid",
            "commit",
            "-qm",
            "fixture",
        ],
        cwd=repository,
        check=True,
    )
    monkeypatch.setattr(source_release, "REQUIRED_FILES", {"README.md"})

    output = tmp_path / "output"
    manifest = source_release.build_archive(output, repository)
    archive = output / str(manifest["archive"])
    assert archive.is_file()
    assert manifest["commit_sha"] == subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=repository, text=True
    ).strip()
    assert manifest["sha256"] == hashlib.sha256(archive.read_bytes()).hexdigest()
    assert json.loads((output / "source-release-manifest.json").read_text()) == manifest
    assert (output / f"{archive.name}.sha256").read_text(encoding="ascii") == (
        f"{manifest['sha256']}  {archive.name}\n"
    )

    (repository / "untracked.txt").write_text("dirty\n", encoding="utf-8")
    with pytest.raises(source_release.ReleaseCheckError, match="clean committed"):
        source_release.build_archive(tmp_path / "second-output", repository)
