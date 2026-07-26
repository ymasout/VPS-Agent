from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from app.recovery import FORMAT_VERSION, KEY_TABLE_ALLOWLIST, BackupManifest


def manifest_values() -> dict:
    return {
        "format_version": FORMAT_VERSION,
        "instance_id": "local-console",
        "created_at": datetime.now(timezone.utc),
        "control_plane_version": "0.6.1",
        "control_plane_commit_sha": "a" * 40,
        "control_plane_build_time": "2026-07-26T00:00:00Z",
        "alembic_revision": ["0017_m5_runbook_drafts"],
        "expected_alembic_revision": ["0017_m5_runbook_drafts"],
        "postgres_major": 16,
        "database_name": "vps_agent",
        "database_role": "vps_agent",
        "required_extensions": [],
        "key_table_counts": {name: 0 for name in KEY_TABLE_ALLOWLIST},
        "active_operation_count": 0,
        "snapshot_note": (
            "consistent snapshot may include operations that were in flight when backup started"
        ),
        "label": "test",
        "dump": {"name": "postgres.dump", "sha256": "b" * 64, "size_bytes": 42},
    }


def test_manifest_uses_a_fixed_key_table_allowlist() -> None:
    manifest = BackupManifest.model_validate(manifest_values())
    assert tuple(manifest.key_table_counts) == KEY_TABLE_ALLOWLIST


def test_manifest_rejects_unknown_metadata() -> None:
    values = manifest_values()
    values["database_password"] = "must-not-be-recorded"
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        BackupManifest.model_validate(values)


def test_manifest_rejects_invalid_dump_hash() -> None:
    values = manifest_values()
    values["dump"]["sha256"] = "not-a-hash"
    with pytest.raises(ValidationError):
        BackupManifest.model_validate(values)


def test_manifest_rejects_unbounded_table_metadata() -> None:
    values = manifest_values()
    values["key_table_counts"]["secret_table"] = 1
    with pytest.raises(ValidationError, match="fixed M6.1 allowlist"):
        BackupManifest.model_validate(values)
