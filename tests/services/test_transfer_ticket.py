import secrets
import uuid

import jwt
import pytest

from aistack.commons.exceptions import InvalidTicket
from aistack.services.transfer_ticket import (
    SIGNING_KEY_BYTES,
    DownloadTicket,
    TicketSigner,
    UploadTicket,
)

KEY = secrets.token_bytes(SIGNING_KEY_BYTES)

UPLOAD = UploadTicket(machine_id=uuid.uuid4(), user_id=uuid.uuid4(), skill_name="wizard",
                      origin="https://github.com/mattpocock/skills")
DOWNLOAD = DownloadTicket(machine_id=uuid.uuid4(), skill_version_id=uuid.uuid4())


@pytest.fixture(name="signer")
def signer_fixture() -> TicketSigner:
    return TicketSigner(KEY)


def test_an_upload_ticket_round_trips(signer):
    assert signer.verified_upload(signer.sign_upload(UPLOAD)) == UPLOAD


def test_an_upload_ticket_without_an_origin_round_trips(signer):
    ticket = UploadTicket(UPLOAD.machine_id, UPLOAD.user_id, "wizard", None)

    assert signer.verified_upload(signer.sign_upload(ticket)) == ticket


def test_a_download_ticket_round_trips(signer):
    assert signer.verified_download(signer.sign_download(DOWNLOAD)) == DOWNLOAD


def test_a_ticket_is_safe_to_put_in_a_url_path(signer):
    token = signer.sign_upload(UPLOAD)

    assert all(character.isalnum() or character in "-_." for character in token)


def test_a_ticket_for_one_direction_is_refused_by_the_other(signer):
    with pytest.raises(InvalidTicket):
        signer.verified_upload(signer.sign_download(DOWNLOAD))
    with pytest.raises(InvalidTicket):
        signer.verified_download(signer.sign_upload(UPLOAD))


def test_an_expired_ticket_says_how_to_get_a_fresh_one():
    expired = TicketSigner(KEY, lifetime_seconds=-1)

    with pytest.raises(InvalidTicket) as upload:
        expired.verified_upload(expired.sign_upload(UPLOAD))
    with pytest.raises(InvalidTicket) as download:
        expired.verified_download(expired.sign_download(DOWNLOAD))

    assert "expired" in str(upload.value) and "push_skill" in str(upload.value)
    assert "expired" in str(download.value) and "get_skill" in str(download.value)


def test_a_ticket_signed_with_another_key_is_refused(signer):
    """What a restart does to every outstanding URL, and what a forger without the key gets."""
    other = TicketSigner(secrets.token_bytes(SIGNING_KEY_BYTES))

    with pytest.raises(InvalidTicket):
        signer.verified_upload(other.sign_upload(UPLOAD))


def test_a_ticket_whose_payload_was_edited_is_refused(signer):
    """Change the skill name, keep the signature: the classic attempt."""
    header, _, signature = signer.sign_upload(UPLOAD).split(".")
    _, forged_payload, _ = signer.sign_upload(
        UploadTicket(UPLOAD.machine_id, UPLOAD.user_id, "someone-elses-skill", None)).split(".")

    with pytest.raises(InvalidTicket):
        signer.verified_upload(f"{header}.{forged_payload}.{signature}")


def test_an_unsigned_ticket_is_refused(signer):
    """`alg: none` is a valid JWT and a forgery. The pinned algorithm list is what stops it."""
    claims = jwt.decode(signer.sign_upload(UPLOAD), options={"verify_signature": False})
    unsigned = jwt.encode(claims, key=None, algorithm="none")

    with pytest.raises(InvalidTicket):
        signer.verified_upload(unsigned)


@pytest.mark.parametrize("claim", ["exp", "aud", "sub"])
def test_a_ticket_missing_a_required_claim_is_refused(signer, claim):
    claims = jwt.decode(signer.sign_upload(UPLOAD), options={"verify_signature": False})
    del claims[claim]

    with pytest.raises(InvalidTicket):
        signer.verified_upload(jwt.encode(claims, KEY, algorithm="HS256"))


@pytest.mark.parametrize("token", ["", "not-a-ticket", "a.b.c", "....", "a" * 5000])
def test_garbage_is_refused_without_being_echoed(signer, token):
    with pytest.raises(InvalidTicket) as rejection:
        signer.verified_upload(token)

    if token:
        assert token not in str(rejection.value)


def test_a_rejection_never_repeats_the_ticket(signer):
    expired = TicketSigner(KEY, lifetime_seconds=-1)
    token = expired.sign_upload(UPLOAD)

    with pytest.raises(InvalidTicket) as rejection:
        signer.verified_upload(token)

    assert token not in str(rejection.value)
    assert token.split(".")[2] not in str(rejection.value)
