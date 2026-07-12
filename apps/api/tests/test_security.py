from app.security import generate_token, hash_token


def test_generated_tokens_are_unique_and_prefixed() -> None:
    first = generate_token("reg")
    second = generate_token("reg")

    assert first.startswith("reg_")
    assert first != second
    assert hash_token(first) != hash_token(second)
    assert first not in hash_token(first)
