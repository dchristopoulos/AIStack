import secrets
import uuid

import jwt
import pytest

from aistack.commons.exceptions import InvalidTicket
from aistack.db.models.coding_agent import CodingAgent
from aistack.db.models.harness import Harness
from aistack.services.transfer_ticket import (
    SIGNING_KEY_BYTES,
    DashboardHolder,
    DownloadTicket,
    ProjectFileEditTicket,
    ProjectFileUploadTicket,
    RuleDownloadTicket,
    RuleUploadTicket,
    TicketSigner,
    UploadTicket,
)

KEY = secrets.token_bytes(SIGNING_KEY_BYTES)

TOKEN_PREFIX = "0123456789abcdef"
UPLOAD = UploadTicket(machine_id=uuid.uuid4(), user_id=uuid.uuid4(), token_prefix=TOKEN_PREFIX,
                      skill_name="wizard", origin="https://github.com/mattpocock/skills",
                      harness=Harness.AGENTS)
DOWNLOAD = DownloadTicket(machine_id=uuid.uuid4(), token_prefix=TOKEN_PREFIX,
                          skill_version_id=uuid.uuid4())
HOLDER = DashboardHolder(user_id=uuid.uuid4(), machine_id=uuid.uuid4(),
                         token_prefix=TOKEN_PREFIX)


@pytest.fixture(name="signer")
def signer_fixture() -> TicketSigner:
    return TicketSigner(KEY)


def test_an_upload_ticket_round_trips(signer):
    assert signer.verified_upload(signer.sign_upload(UPLOAD)) == UPLOAD


def test_an_upload_ticket_without_an_origin_round_trips(signer):
    ticket = UploadTicket(UPLOAD.machine_id, UPLOAD.user_id, TOKEN_PREFIX, "wizard", None,
                          Harness.CLAUDE_CODE)

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
        UploadTicket(UPLOAD.machine_id, UPLOAD.user_id, TOKEN_PREFIX, "someone-elses-skill",
                     None, Harness.CLAUDE_CODE)).split(".")

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


@pytest.mark.parametrize(("purpose", "claims"), [
    ("upload", {"sub": "not-a-uuid"}),
    ("upload", {"user_id": "not-a-uuid"}),
    ("upload", {"user_id": None}),
    ("upload", {"skill_name": ...}),
    ("download", {"sub": "not-a-uuid"}),
    ("download", {"skill_version_id": ...}),
])
def test_a_correctly_signed_ticket_with_malformed_claims_is_still_just_not_valid(purpose,
                                                                              claims):
    """Reachable only with the key. It is still a rejection, never an unhandled error."""
    signer = TicketSigner(KEY)
    token = signer.sign_upload(UPLOAD) if purpose == "upload" else signer.sign_download(DOWNLOAD)
    forged = jwt.decode(token, options={"verify_signature": False})
    for claim, value in claims.items():
        if value is ...:
            del forged[claim]
        else:
            forged[claim] = value
    resigned = jwt.encode(forged, KEY, algorithm="HS256")

    with pytest.raises(InvalidTicket, match="not valid"):
        (signer.verified_upload if purpose == "upload" else signer.verified_download)(resigned)


# --- dashboard links and sessions --------------------------------------------------------------

def test_a_dashboard_link_names_the_computer_that_asked_for_it_and_works_once(signer):
    link = signer.sign_dashboard_link(HOLDER)

    assert signer.verified_dashboard_link(link) == HOLDER
    with pytest.raises(InvalidTicket):
        signer.verified_dashboard_link(link)


def test_an_ended_session_is_refused_and_others_are_not(signer):
    ended, kept = signer.sign_dashboard_session(HOLDER), signer.sign_dashboard_session(HOLDER)

    signer.end_dashboard_session(ended)

    with pytest.raises(InvalidTicket):
        signer.verified_dashboard_session(ended)
    assert signer.verified_dashboard_session(kept) == HOLDER


def test_ending_something_that_is_not_a_session_ends_nothing(signer):
    link = signer.sign_dashboard_link(HOLDER)

    signer.end_dashboard_session(link)
    signer.end_dashboard_session("nonsense")

    assert signer.verified_dashboard_link(link) == HOLDER


def test_a_session_from_before_tickets_named_their_computer_is_refused(signer):
    """One that names only its user cannot be held to a computer, so it is not a session."""
    claims = jwt.decode(signer.sign_dashboard_session(HOLDER), options={"verify_signature": False})
    del claims["mid"], claims["tkh"]

    with pytest.raises(InvalidTicket):
        signer.verified_dashboard_session(jwt.encode(claims, KEY, algorithm="HS256"))


# --- rule text (ADR-0036) ----------------------------------------------------------------------

RULE_UPLOAD = RuleUploadTicket(machine_id=uuid.uuid4(), user_id=uuid.uuid4(),
                               token_prefix=TOKEN_PREFIX, rule_name="house-style",
                               agent=CodingAgent.CODEX, project_id=uuid.uuid4(), backup=True)
RULE_DOWNLOAD = RuleDownloadTicket(machine_id=uuid.uuid4(), token_prefix=TOKEN_PREFIX,
                                   rule_revision_id=uuid.uuid4(), agent=CodingAgent.CLAUDE_CODE)


FILE_UPLOAD = ProjectFileUploadTicket(machine_id=uuid.uuid4(), token_prefix=TOKEN_PREFIX,
                                      project_file_id=uuid.uuid4())
FILE_EDIT = ProjectFileEditTicket(machine_id=uuid.uuid4(), token_prefix=TOKEN_PREFIX,
                                  project_file_edit_id=uuid.uuid4())


def test_project_file_tickets_round_trip(signer):
    assert signer.verified_project_file_upload(
        signer.sign_project_file_upload(FILE_UPLOAD)) == FILE_UPLOAD
    assert signer.verified_project_file_edit(
        signer.sign_project_file_edit(FILE_EDIT)) == FILE_EDIT


def test_rule_tickets_round_trip(signer):
    assert signer.verified_rule_upload(signer.sign_rule_upload(RULE_UPLOAD)) == RULE_UPLOAD
    assert signer.verified_rule_download(
        signer.sign_rule_download(RULE_DOWNLOAD)) == RULE_DOWNLOAD


def test_each_ticket_opens_only_its_own_purpose(signer):
    """The audience is the purpose: no skill ticket reads or writes a rule, nor the reverse."""
    signed = {"upload": signer.sign_upload(UPLOAD), "download": signer.sign_download(DOWNLOAD),
              "rule_upload": signer.sign_rule_upload(RULE_UPLOAD),
              "rule_download": signer.sign_rule_download(RULE_DOWNLOAD),
              "file_upload": signer.sign_project_file_upload(FILE_UPLOAD),
              "file_edit": signer.sign_project_file_edit(FILE_EDIT)}
    verifiers = {"upload": signer.verified_upload, "download": signer.verified_download,
                 "rule_upload": signer.verified_rule_upload,
                 "rule_download": signer.verified_rule_download,
                 "file_upload": signer.verified_project_file_upload,
                 "file_edit": signer.verified_project_file_edit}
    # Every claim any purpose reads, so only the audience tells them apart.
    every_claim = {}
    for token in signed.values():
        every_claim |= jwt.decode(token, options={"verify_signature": False})
    for purpose, token in signed.items():
        audience = jwt.decode(token, options={"verify_signature": False})["aud"]
        forged = jwt.encode(every_claim | {"aud": audience}, KEY, algorithm="HS256")
        for other, verify in verifiers.items():
            if other != purpose:
                with pytest.raises(InvalidTicket):
                    verify(token)
                with pytest.raises(InvalidTicket):
                    verify(forged)


@pytest.mark.parametrize("claims", [{"agent": "gemini"}, {"backup": "yes"}, {"rule_name": ...},
                                    {"project_id": "not-a-uuid"}])
def test_a_rule_upload_ticket_with_malformed_claims_is_not_valid(claims):
    signer = TicketSigner(KEY)
    forged = jwt.decode(signer.sign_rule_upload(RULE_UPLOAD), options={"verify_signature": False})
    for claim, value in claims.items():
        if value is ...:
            del forged[claim]
        else:
            forged[claim] = value
    with pytest.raises(InvalidTicket, match="not valid"):
        signer.verified_rule_upload(jwt.encode(forged, KEY, algorithm="HS256"))
