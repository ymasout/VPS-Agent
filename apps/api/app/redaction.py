import re

REDACTION_RULES = (
    re.compile(r"(?i)(authorization\s*[:=]\s*(?:bearer\s+)?)[^\s,;]+"),
    re.compile(
        r"(?i)((?:password|passwd|token|secret|api[_-]?key|cookie|webhook)\s*[:=]\s*)"
        r"[^\s,;]+"
    ),
    re.compile(r"(?i)(https://[^\s/]+/(?:robot/send|webhook)[^\s?]*\?[^\s]*?access_token=)[^&\s]+"),
    re.compile(
        r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----.*?"
        r"-----END (?:RSA |EC |OPENSSH )?PRIVATE KEY-----",
        re.DOTALL,
    ),
)


def redact_text(value: str) -> tuple[str, bool]:
    """对日志和外部文本做二次脱敏；Agent 侧仍需在上传前先脱敏。"""

    redacted = value
    for rule in REDACTION_RULES:
        redacted = rule.sub(
            lambda match: f"{match.group(1) if match.lastindex else ''}[REDACTED]", redacted
        )
    return redacted, redacted != value


def truncate_utf8(value: str, max_bytes: int) -> tuple[str, bool]:
    encoded = value.encode("utf-8")
    if len(encoded) <= max_bytes:
        return value, False
    return encoded[:max_bytes].decode("utf-8", errors="ignore"), True


def truncate_lines(value: str, max_lines: int) -> tuple[str, bool]:
    lines = value.splitlines(keepends=True)
    if len(lines) <= max_lines:
        return value, False
    return "".join(lines[:max_lines]), True
