import base64
import hashlib
import secrets

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


def generate_token(prefix: str) -> str:
    return f"{prefix}_{secrets.token_urlsafe(32)}"


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def operation_signing_message(fields: list[str]) -> bytes:
    """固定顺序、固定分隔的 v1 签名输入，禁止把自由 JSON 纳入任务。"""

    return "\n".join(fields).encode("utf-8")


def sign_operation(private_key_base64: str, fields: list[str]) -> str:
    try:
        raw = base64.b64decode(private_key_base64, validate=True)
        key = Ed25519PrivateKey.from_private_bytes(raw)
    except (ValueError, TypeError) as error:
        raise ValueError("invalid Ed25519 operation signing key") from error
    return base64.b64encode(key.sign(operation_signing_message(fields))).decode("ascii")
