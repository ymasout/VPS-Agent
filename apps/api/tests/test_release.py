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
    assert result["version"] == "0.6.1"
    assert result["tag"] == "v0.6.1"
    assert result["agent_module"] == "github.com/ymasout/VPS-Agent/apps/agent"
    assert result["schema_revision"] == "0020_m6_named_approval"


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
