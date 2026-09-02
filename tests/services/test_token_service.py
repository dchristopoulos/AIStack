from pydantic import SecretStr

from aistack.services.token_service import (TOKEN_PREFIX, generate_machine_token, hash_token,
                                            matches_invite_code)


def test_generated_tokens_are_prefixed_and_unique():
    first = generate_machine_token()
    second = generate_machine_token()

    assert first.startswith(TOKEN_PREFIX)
    assert first != second
    assert len(first) > len(TOKEN_PREFIX) + 32


def test_hash_is_stable_lowercase_hex_of_the_whole_token():
    token = generate_machine_token()

    digest = hash_token(token)

    assert digest == hash_token(token)
    assert len(digest) == 64
    assert digest == digest.lower()
    # The prefix is hashed with the rest, so verification never has to strip anything.
    assert digest != hash_token(token.removeprefix(TOKEN_PREFIX))


def test_invite_code_comparison_accepts_only_the_exact_code():
    configured = SecretStr("s3cret-code")

    assert matches_invite_code("s3cret-code", configured)
    assert not matches_invite_code("s3cret-cod", configured)
    assert not matches_invite_code("s3cret-code ", configured)
    assert not matches_invite_code("", configured)
