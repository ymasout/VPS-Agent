#!/usr/bin/env python3
"""Build a secret-safe source archive from Git tracked files only."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
REQUIRED_FILES = {
    "LICENSE",
    "LICENSES/AGPL-3.0-only.txt",
    "LICENSES/Apache-2.0.txt",
    "LICENSING.md",
    "NOTICE",
    "THIRD_PARTY_NOTICES.md",
    "REUSE.toml",
    "SECURITY.md",
    "CONTRIBUTING.md",
    "CODE_OF_CONDUCT.md",
    "CHANGELOG.md",
    "release/release.json",
    "docs/RELEASE_COMPATIBILITY.md",
    "docs/RELEASE_PROCESS.md",
    "docs/M6_RELEASE_DISTRIBUTION.md",
}
FORBIDDEN_PARTS = {
    ".git",
    ".next",
    ".pytest_cache",
    ".recovery-audit",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "backups",
    "dist",
    "node_modules",
}
FORBIDDEN_SUFFIXES = {
    ".backup",
    ".db",
    ".dump",
    ".key",
    ".log",
    ".p12",
    ".pem",
    ".pfx",
    ".sqlite",
    ".sqlite3",
}
ALLOWED_ENV_FILES = {
    ".env.example",
    "deploy/.env.production.example",
    "deploy/release/.env.release.example",
}
TOKEN_PATTERNS = {
    "aws_access_key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "github_token": re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{40,})\b"),
    "slack_token": re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{20,}\b"),
    "telegram_bot_token": re.compile(r"\b[0-9]{6,}:[A-Za-z0-9_-]{30,}\b"),
}
PRIVATE_KEY_PATTERN = re.compile(
    r"-----BEGIN ([A-Z0-9 ]*PRIVATE KEY)-----(.*?)"
    r"-----END \1-----",
    re.DOTALL,
)


class ReleaseCheckError(RuntimeError):
    pass


def run_git(*args: str, root: Path = ROOT) -> bytes:
    return subprocess.check_output(["git", *args], cwd=root)


def candidate_files(root: Path = ROOT) -> list[str]:
    output = run_git(
        "ls-files",
        "--cached",
        "--others",
        "--exclude-standard",
        "-z",
        root=root,
    )
    return sorted(item for item in output.decode("utf-8").split("\0") if item)


def validate_path(relative: str) -> list[str]:
    path = PurePosixPath(relative)
    lowered_parts = {part.lower() for part in path.parts}
    errors: list[str] = []
    if path.is_absolute() or ".." in path.parts:
        errors.append("path escapes repository")
    if lowered_parts & FORBIDDEN_PARTS:
        errors.append("forbidden generated or sensitive directory")
    lowered = relative.lower()
    if path.name.lower().startswith(".env") and relative not in ALLOWED_ENV_FILES:
        errors.append("runtime environment file")
    if any(lowered.endswith(suffix) for suffix in FORBIDDEN_SUFFIXES):
        errors.append("forbidden sensitive file type")
    return errors


def scan_text(relative: str, text: str) -> list[str]:
    errors = [name for name, pattern in TOKEN_PATTERNS.items() if pattern.search(text)]
    for match in PRIVATE_KEY_PATTERN.finditer(text):
        body = re.sub(r"\s+", "", match.group(2))
        if len(body) >= 128:
            errors.append("private_key")
    return errors


def validate_repository(root: Path = ROOT) -> dict[str, object]:
    files = candidate_files(root)
    errors: list[str] = []
    scanned_text_files = 0
    for relative in files:
        path = root / relative
        for reason in validate_path(relative):
            errors.append(f"{relative}: {reason}")
        if path.is_symlink():
            errors.append(f"{relative}: symbolic links are not allowed in source releases")
            continue
        if not path.is_file():
            errors.append(f"{relative}: tracked path is not a regular file")
            continue
        data = path.read_bytes()
        if b"\0" in data:
            continue
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            continue
        scanned_text_files += 1
        for finding in scan_text(relative, text):
            errors.append(f"{relative}: possible {finding}")
    missing = sorted(REQUIRED_FILES - set(files))
    errors.extend(f"{item}: required release governance file is missing" for item in missing)
    if errors:
        raise ReleaseCheckError("\n".join(errors))
    return {
        "file_count": len(files),
        "scanned_text_file_count": scanned_text_files,
        "required_files_present": sorted(REQUIRED_FILES),
        "source": "git tracked files plus untracked non-ignored review files",
    }


def ensure_clean(root: Path = ROOT) -> None:
    status = run_git("status", "--porcelain=v1", root=root).decode("utf-8").strip()
    if status:
        raise ReleaseCheckError(
            "source archive requires a clean committed worktree; "
            "uncommitted changes:\n" + status
        )


def build_archive(output_dir: Path, root: Path = ROOT) -> dict[str, object]:
    ensure_clean(root)
    validate_repository(root)
    commit = run_git("rev-parse", "HEAD", root=root).decode("ascii").strip()
    output_dir.mkdir(parents=True, exist_ok=True)
    archive = output_dir / f"vps-agent-source-{commit[:12]}.tar.gz"
    prefix = f"vps-agent-source-{commit[:12]}/"
    subprocess.run(
        [
            "git",
            "archive",
            "--format=tar.gz",
            f"--prefix={prefix}",
            f"--output={archive}",
            "HEAD",
        ],
        cwd=root,
        check=True,
    )
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    manifest = {
        "archive": archive.name,
        "commit_sha": commit,
        "sha256": digest,
        "size_bytes": archive.stat().st_size,
    }
    (output_dir / "source-release-manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (output_dir / f"{archive.name}.sha256").write_text(
        f"{digest}  {archive.name}\n",
        encoding="ascii",
    )
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("check")
    build = subparsers.add_parser("build")
    build.add_argument("--output-dir", type=Path, default=ROOT / "dist")
    args = parser.parse_args()
    try:
        result = (
            validate_repository(ROOT)
            if args.command == "check"
            else build_archive(args.output_dir.resolve(), ROOT)
        )
    except (ReleaseCheckError, subprocess.CalledProcessError) as error:
        print(f"source release check failed: {error}", file=os.sys.stderr)
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
