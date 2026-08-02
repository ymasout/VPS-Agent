import importlib.util
import json
import tarfile
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "stage_release.py"
SPEC = importlib.util.spec_from_file_location("stage_release", SCRIPT)
assert SPEC and SPEC.loader
stage_release = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(stage_release)
RELEASE_SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "release.py"
RELEASE_SPEC = importlib.util.spec_from_file_location("release_for_stage", RELEASE_SCRIPT)
assert RELEASE_SPEC and RELEASE_SPEC.loader
release = importlib.util.module_from_spec(RELEASE_SPEC)
RELEASE_SPEC.loader.exec_module(release)


def member(name: str, kind: bytes = tarfile.REGTYPE, size: int = 0) -> tarfile.TarInfo:
    value = tarfile.TarInfo(name)
    value.type = kind
    value.size = size
    return value


def valid_members() -> list[tarfile.TarInfo]:
    top = "vps-agent-0.6.1"
    result = [member(top, tarfile.DIRTYPE)]
    directories: set[str] = set()
    for relative in sorted(stage_release.ALLOWED_FILES):
        path = Path(top) / relative
        for parent in path.parents:
            if parent.as_posix() == "." or parent.as_posix() == top:
                continue
            directories.add(parent.as_posix())
        result.append(member(path.as_posix()))
    result.extend(member(path, tarfile.DIRTYPE) for path in sorted(directories))
    return result


def test_stage_allowlist_matches_release_bundle_contract() -> None:
    assert set(release.REQUIRED_BUNDLE_FILES) | set(release.GENERATED_BUNDLE_FILES) == (
        stage_release.ALLOWED_FILES
    )


def test_archive_member_allowlist_accepts_exact_bundle() -> None:
    assert stage_release.validate_members(valid_members()) == "vps-agent-0.6.1"


@pytest.mark.parametrize(
    ("bad_member", "message"),
    [
        (member("../escape"), "escapes"),
        (member("/absolute"), "escapes"),
        (member("vps-agent-0.6.1/link", tarfile.SYMTYPE), "links"),
        (member("vps-agent-0.6.1/hard", tarfile.LNKTYPE), "links"),
        (member("vps-agent-0.6.1/device", tarfile.CHRTYPE), "special"),
    ],
)
def test_archive_member_validation_rejects_unsafe_entries(
    bad_member: tarfile.TarInfo, message: str
) -> None:
    with pytest.raises(stage_release.StageError, match=message):
        stage_release.validate_members([*valid_members(), bad_member])


def test_archive_member_validation_rejects_duplicate_and_extra_files() -> None:
    values = valid_members()
    with pytest.raises(stage_release.StageError, match="duplicate"):
        stage_release.validate_members([*values, values[1]])
    with pytest.raises(stage_release.StageError, match="allowlist"):
        stage_release.validate_members([*values, member("vps-agent-0.6.1/extra")])
    with pytest.raises(stage_release.StageError, match="directory allowlist"):
        stage_release.validate_members(
            [*values, member("vps-agent-0.6.1/unexpected", tarfile.DIRTYPE)]
        )


def test_images_env_requires_exact_order_and_canonical_digests(tmp_path: Path) -> None:
    values = {
        key: f"ghcr.io/ymasout/{key.lower()}@sha256:" + "a" * 64
        for key in stage_release.IMAGE_KEYS
    }
    path = tmp_path / "images.env"
    path.write_text("".join(f"{key}={value}\n" for key, value in values.items()), encoding="ascii")
    assert stage_release.parse_images_env(path) == values
    reversed_lines = "".join(f"{key}={value}\n" for key, value in reversed(values.items()))
    path.write_text(reversed_lines, encoding="ascii")
    with pytest.raises(stage_release.StageError, match="order"):
        stage_release.parse_images_env(path)


def test_extracted_manifest_must_match_images_env(tmp_path: Path) -> None:
    top = "vps-agent-0.6.1"
    base = tmp_path / top
    for relative in stage_release.ALLOWED_FILES:
        path = base / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("placeholder\n", encoding="utf-8")
    images = {
        key: f"ghcr.io/ymasout/{key.lower()}@sha256:" + "a" * 64
        for key in stage_release.IMAGE_KEYS
    }
    (base / "deploy/release/images.env").write_text(
        "".join(f"{key}={value}\n" for key, value in images.items()), encoding="ascii"
    )
    manifest = {
        "format_version": "m6.4d-release-v1",
        "version": "0.6.1",
        "tag": "v0.6.1",
        "commit_sha": "a" * 40,
        "schema_revision": "0020_m6_named_approval",
        "images": images,
        "created_at": "2026-08-01T00:00:00Z",
    }
    (base / "release-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (base / "release/release.json").write_text(
        json.dumps(
            {
                "version": "0.6.1",
                "tag": "v0.6.1",
                "schema_revision": "0020_m6_named_approval",
            }
        ),
        encoding="utf-8",
    )
    assert stage_release.validate_extracted(tmp_path, top)["version"] == "0.6.1"
    manifest["images"] = {**images, stage_release.IMAGE_KEYS[0]: "bad"}
    (base / "release-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(stage_release.StageError, match="does not match"):
        stage_release.validate_extracted(tmp_path, top)


def test_extracted_manifest_must_match_release_spec(tmp_path: Path) -> None:
    test_extracted_manifest_must_match_images_env(tmp_path)
    manifest_path = tmp_path / "vps-agent-0.6.1/release-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["images"] = stage_release.parse_images_env(
        tmp_path / "vps-agent-0.6.1/deploy/release/images.env"
    )
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    spec_path = tmp_path / "vps-agent-0.6.1/release/release.json"
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    spec["schema_revision"] = "wrong_revision"
    spec_path.write_text(json.dumps(spec), encoding="utf-8")
    with pytest.raises(stage_release.StageError, match="release/release.json"):
        stage_release.validate_extracted(tmp_path, "vps-agent-0.6.1")


def test_checksum_file_is_strict_and_unique(tmp_path: Path) -> None:
    path = tmp_path / "archive.sha256"
    path.write_text(f"{'a' * 64}  release.tar.gz\n", encoding="ascii")
    assert stage_release.expected_checksum(path, "release.tar.gz") == "a" * 64
    path.write_text(f"{'a' * 64}  release.tar.gz\n{'b' * 64}  release.tar.gz\n", encoding="ascii")
    with pytest.raises(stage_release.StageError, match="exactly once"):
        stage_release.expected_checksum(path, "release.tar.gz")
