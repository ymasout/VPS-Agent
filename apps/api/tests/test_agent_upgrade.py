import argparse
import importlib.util
import json
import os
import shutil
from collections import namedtuple
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "agent_upgrade.py"
SPEC = importlib.util.spec_from_file_location("agent_upgrade", SCRIPT)
assert SPEC and SPEC.loader
agent_upgrade = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(agent_upgrade)


def write(path: Path, value: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8")
    return path


def transaction_args(
    tmp_path: Path, boot_id: str = "11111111-1111-4111-8111-111111111111"
) -> argparse.Namespace:
    return argparse.Namespace(
        state_dir=tmp_path / "state",
        candidate_binary=write(tmp_path / "candidate/binary", "new-binary"),
        candidate_env=write(tmp_path / "candidate/env", "NEW=value"),
        candidate_unit=write(tmp_path / "candidate/unit", "new-unit"),
        binary=write(tmp_path / "live/binary", "old-binary"),
        env=write(tmp_path / "live/env", "OLD=secret"),
        unit=write(tmp_path / "live/unit", "old-unit"),
        current_version="0.4.2",
        target_version="0.6.1",
        boot_id=boot_id,
        transaction_id="12345678-1234-4123-8123-123456789abc",
    )


def metadata() -> dict[str, object]:
    return {
        "format_version": "vps-agent-upgrade-v1",
        "repository": "github.com/ymasout/VPS-Agent",
        "target_version": "0.6.1",
        "target_tag": "v0.6.1",
        "commit_sha": "a" * 40,
        "upgrade_from": ["0.4.2"],
    }


def test_upgrade_metadata_is_strict_and_exact(tmp_path: Path) -> None:
    path = tmp_path / "agent-upgrade.json"
    path.write_text(json.dumps(metadata()), encoding="utf-8")
    assert agent_upgrade.validate_metadata(path, "0.4.2", "0.6.1")["target_tag"] == "v0.6.1"
    with pytest.raises(agent_upgrade.UpgradeError, match="not supported"):
        agent_upgrade.validate_metadata(path, "0.3.3", "0.6.1")
    value = metadata()
    value["unexpected"] = True
    path.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(agent_upgrade.UpgradeError, match="strict schema"):
        agent_upgrade.validate_metadata(path, "0.4.2", "0.6.1")


def test_prepare_and_failed_activation_rollback_preserve_previous_files(tmp_path: Path) -> None:
    args = transaction_args(tmp_path)
    agent_upgrade.prepare(args)
    assert args.binary.read_text(encoding="utf-8") == "new-binary"
    assert args.env.read_text(encoding="utf-8") == "NEW=value"
    assert (args.state_dir / "transaction.json").is_file()
    result = agent_upgrade.rollback(args.state_dir)
    assert result["rolled_back"] is True
    assert args.binary.read_text(encoding="utf-8") == "old-binary"
    assert args.env.read_text(encoding="utf-8") == "OLD=secret"
    assert not (args.state_dir / "transaction.json").exists()
    assert not (args.state_dir / "transactions" / args.transaction_id).exists()


def test_rollback_rejects_tampered_previous_generation(tmp_path: Path) -> None:
    args = transaction_args(tmp_path)
    agent_upgrade.prepare(args)
    previous = args.state_dir / "transactions" / args.transaction_id / "previous"
    (previous / "binary").write_text("tampered", encoding="utf-8")
    with pytest.raises(agent_upgrade.UpgradeError, match="integrity check failed"):
        agent_upgrade.rollback(args.state_dir)
    assert args.binary.read_text(encoding="utf-8") == "new-binary"
    assert (args.state_dir / "transaction.json").is_file()


def test_commit_keeps_exactly_one_previous_generation(tmp_path: Path) -> None:
    args = transaction_args(tmp_path)
    agent_upgrade.prepare(args)
    result = agent_upgrade.commit(args.state_dir)
    assert result["audit_code"] == "upgrade_committed"
    previous = args.state_dir / "previous"
    assert {path.name for path in previous.iterdir()} == {"binary", "env", "unit", "manifest.json"}
    assert (previous / "binary").read_text(encoding="utf-8") == "old-binary"
    assert not (args.state_dir / "transaction.json").exists()


def test_rollback_recovers_interrupted_previous_promotion(tmp_path: Path) -> None:
    first = transaction_args(tmp_path / "first")
    agent_upgrade.prepare(first)
    agent_upgrade.commit(first.state_dir)

    second = transaction_args(tmp_path / "second")
    second.state_dir = first.state_dir
    agent_upgrade.prepare(second)
    source = second.state_dir / "transactions" / second.transaction_id / "previous"
    replacement = second.state_dir / ".previous-next"
    shutil.copytree(source, replacement)
    os.replace(second.state_dir / "previous", second.state_dir / ".previous-old")

    result = agent_upgrade.rollback(second.state_dir)
    assert result["rolled_back"] is True
    assert (second.state_dir / "previous").is_dir()
    assert not replacement.exists()
    assert not (second.state_dir / ".previous-old").exists()
    assert second.binary.read_text(encoding="utf-8") == "old-binary"


def test_cross_boot_recovery_rolls_back_but_same_boot_does_not(tmp_path: Path) -> None:
    args = transaction_args(tmp_path)
    agent_upgrade.prepare(args)
    same = agent_upgrade.recover_if_new_boot(
        args.state_dir, "11111111-1111-4111-8111-111111111111"
    )
    assert same["rolled_back"] is False
    assert args.binary.read_text(encoding="utf-8") == "new-binary"
    recovered = agent_upgrade.recover_if_new_boot(
        args.state_dir, "44444444-4444-4444-8444-444444444444"
    )
    assert recovered["rolled_back"] is True
    assert args.binary.read_text(encoding="utf-8") == "old-binary"


def test_prepare_rejects_symlink_sources(tmp_path: Path) -> None:
    args = transaction_args(tmp_path)
    target = tmp_path / "candidate/real"
    target.write_text("binary", encoding="utf-8")
    args.candidate_binary.unlink()
    try:
        args.candidate_binary.symlink_to(target)
    except OSError:
        pytest.skip("symlinks are unavailable")
    with pytest.raises(agent_upgrade.UpgradeError, match="non-symlink"):
        agent_upgrade.prepare(args)


def test_prepare_rejects_oversized_candidate(tmp_path: Path) -> None:
    args = transaction_args(tmp_path)
    with args.candidate_binary.open("wb") as handle:
        handle.truncate(agent_upgrade.MAX_SIZES["binary"] + 1)
    with pytest.raises(agent_upgrade.UpgradeError, match="size limit"):
        agent_upgrade.prepare(args)


def test_prepare_rejects_insufficient_free_space(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    args = transaction_args(tmp_path)
    usage = namedtuple("usage", "total used free")
    monkeypatch.setattr(agent_upgrade.shutil, "disk_usage", lambda _: usage(100, 99, 1))
    with pytest.raises(agent_upgrade.UpgradeError, match="insufficient free space"):
        agent_upgrade.prepare(args)
