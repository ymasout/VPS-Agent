import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "release.py"
SPEC = importlib.util.spec_from_file_location("release", SCRIPT)
assert SPEC and SPEC.loader
release = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(release)


def test_release_spec_matches_repository_coordinates() -> None:
    result = release.validate_spec()
    assert result["version"] == "0.6.5"
    assert result["tag"] == "v0.6.5"
    assert result["agent_module"] == "github.com/ymasout/VPS-Agent/apps/agent"
    assert result["schema_revision"] == "0020_m6_named_approval"
    assert result["agent_upgrade_from"] == ["0.4.2", "0.6.1", "0.6.3", "0.6.4"]


def test_agent_upgrade_metadata_is_exact_and_commit_bound() -> None:
    spec = release.validate_spec()
    result = release.build_agent_upgrade_metadata(spec, "a" * 40)
    assert result == {
        "format_version": "vps-agent-upgrade-v1",
        "repository": "github.com/ymasout/VPS-Agent",
        "target_version": "0.6.5",
        "target_tag": "v0.6.5",
        "commit_sha": "a" * 40,
        "upgrade_from": ["0.4.2", "0.6.1", "0.6.3", "0.6.4"],
    }
    with pytest.raises(release.ReleaseError, match="full lowercase Git SHA"):
        release.build_agent_upgrade_metadata(spec, "short")


def test_release_digest_validation_is_canonical_and_repository_bound() -> None:
    value = "ghcr.io/ymasout/vps-agent-api@sha256:" + "a" * 64
    assert release.checked_image(value, "ghcr.io/ymasout/vps-agent-api") == value
    with pytest.raises(release.ReleaseError, match="immutable canonical"):
        release.checked_image("ghcr.io/ymasout/vps-agent-api:v0.6.1")
    with pytest.raises(release.ReleaseError, match="repository mismatch"):
        release.checked_image(value, "ghcr.io/attacker/api")


def test_release_action_pin_check_rejects_tags(tmp_path: Path) -> None:
    workflows = tmp_path / ".github" / "workflows"
    workflows.mkdir(parents=True)
    (workflows / "bad.yml").write_text(
        "steps:\n  - uses: actions/checkout@v4\n", encoding="utf-8"
    )
    assert release.validate_action_pins(tmp_path) == [
        ".github/workflows/bad.yml:2: Action is not pinned to a full commit"
    ]
    (workflows / "bad.yml").write_text(
        "steps:\n  - uses: actions/checkout@" + "a" * 40 + "\n", encoding="utf-8"
    )
    assert release.validate_action_pins(tmp_path) == []


def test_vulnerability_workflow_verifies_the_official_asset_name_before_rename() -> None:
    workflow = (release.ROOT / ".github" / "workflows" / "vulnerability-scan.yml").read_text(
        encoding="utf-8"
    )
    assert release.validate_vulnerability_workflow(workflow) == []

    broken = workflow.replace(
        '-o "$RUNNER_TEMP/osv-scanner_linux_amd64"',
        '-o "$RUNNER_TEMP/osv-scanner"',
        1,
    )
    assert release.validate_vulnerability_workflow(broken) == [
        'dependency vulnerability workflow is missing: -o "$RUNNER_TEMP/osv-scanner_linux_amd64"'
    ]


def test_release_bundle_archive_is_reproducible(tmp_path: Path) -> None:
    bundle = tmp_path / "vps-agent-0.6.1"
    (bundle / "nested").mkdir(parents=True)
    (bundle / "release-manifest.json").write_text('{"version":"0.6.1"}\n', encoding="utf-8")
    (bundle / "nested" / "file.txt").write_text("stable\n", encoding="utf-8")
    first = tmp_path / "first.tar.gz"
    second = tmp_path / "second.tar.gz"
    release.build_deterministic_archive(bundle, first, tmp_path, 1_786_000_000)
    release.build_deterministic_archive(bundle, second, tmp_path, 1_786_000_000)
    assert first.read_bytes() == second.read_bytes()


def test_agent_installer_pins_sigstore_identity() -> None:
    installer = (release.ROOT / "scripts" / "install-agent.sh").read_text(encoding="utf-8")
    assert "VPS_AGENT_COSIGN_CERTIFICATE_IDENTITY" not in installer
    assert "VPS_AGENT_COSIGN_OIDC_ISSUER" not in installer
    assert (
        'COSIGN_CERTIFICATE_IDENTITY="https://github.com/ymasout/VPS-Agent/'
        '.github/workflows/formal-release.yml@refs/heads/main"'
    ) in installer


def test_agent_installer_exit_codes_and_boot_recovery_are_fixed() -> None:
    installer = (release.ROOT / "scripts" / "install-agent.sh").read_text(encoding="utf-8")
    for exit_code in (20, 21, 30, 31, 32):
        assert f"exit {exit_code}" in installer
    assert "Type=oneshot" in installer
    assert "Before=vps-agent.service" in installer
    assert "Requires=vps-agent-upgrade-recovery.service" in installer
    assert "After=vps-agent-upgrade-recovery.service" in installer
    assert "agent_registration_failed_after_install" in installer


def test_changelog_valid_iso_date_passes() -> None:
    changelog = "# Changelog\n\n## [0.6.1] - 2026-08-01\n\n### Added\n\n- Feature.\n"
    assert release.validate_changelog(changelog, "0.6.1") == []


def test_changelog_unreleased_current_version_is_rejected() -> None:
    changelog = "# Changelog\n\n## [0.6.1] - Unreleased\n\n### Added\n\n- Feature.\n"
    errors = release.validate_changelog(changelog, "0.6.1")
    assert len(errors) == 1
    assert "Unreleased" in errors[0]


def test_changelog_independent_unreleased_section_is_allowed() -> None:
    changelog = (
        "# Changelog\n\n"
        "## [Unreleased]\n\n"
        "### Added\n\n- Future work.\n\n"
        "## [0.6.1] - 2026-08-01\n\n"
        "### Added\n\n- Feature.\n"
    )
    assert release.validate_changelog(changelog, "0.6.1") == []


def test_changelog_bad_date_format_is_rejected() -> None:
    changelog = "# Changelog\n\n## [0.6.1] - 08-01-2026\n\n### Added\n\n- Feature.\n"
    errors = release.validate_changelog(changelog, "0.6.1")
    assert len(errors) == 1
    assert "ISO" in errors[0]


def test_changelog_missing_version_section_is_rejected() -> None:
    changelog = "# Changelog\n\n## [0.5.0] - 2026-07-01\n\n### Added\n\n- Old feature.\n"
    errors = release.validate_changelog(changelog, "0.6.1")
    assert len(errors) == 1
    assert "does not contain" in errors[0]


def test_changelog_invalid_date_values_are_rejected() -> None:
    changelog = "# Changelog\n\n## [0.6.1] - 2026-13-45\n\n### Added\n\n- Feature.\n"
    errors = release.validate_changelog(changelog, "0.6.1")
    assert len(errors) == 1
    assert "ISO" in errors[0]


def test_changelog_duplicate_release_sections_are_rejected() -> None:
    changelog = (
        "# Changelog\n\n"
        "## [0.6.1] - 2026-08-01\n\n- First.\n\n"
        "## [0.6.1] - 2026-08-02\n\n- Duplicate.\n"
    )
    errors = release.validate_changelog(changelog, "0.6.1")
    assert len(errors) == 1
    assert "exactly one" in errors[0]


def test_changelog_release_date_with_trailing_text_is_rejected() -> None:
    changelog = "# Changelog\n\n## [0.6.1] - 2026-08-01 final\n\n- Feature.\n"
    errors = release.validate_changelog(changelog, "0.6.1")
    assert len(errors) == 1
    assert "ISO" in errors[0]
