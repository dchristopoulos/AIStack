"""An admin's cancel and a holder's join at once: exactly one wins, and the cancel says which."""

import threading
import uuid

from sqlalchemy import func, select

from aistack.commons.exceptions import ValidationError
from aistack.db.engine import build_session_factory
from aistack.db.models.invite import Invite
from aistack.db.models.team import TeamMember
from aistack.services import onboarding_service, team_service
from tests.teams import make_team


def test_a_join_that_lands_during_a_cancel_makes_the_cancel_say_so(postgres_engine,
                                                                   monkeypatch):
    session_factory = build_session_factory(postgres_engine)
    with session_factory.begin() as session:
        admin = onboarding_service.join(session, "dimitris", "laptop", "LINUX").user.user_id
        eve = onboarding_service.join(session, "eve", "laptop", "LINUX").user.user_id
        make_team(session, "acme", admin)
        code = team_service.new_invite_code(session, admin, "acme")
        invite_id = str(session.scalar(select(Invite.invite_id).where(Invite.used_on.is_(None))))

    # The cancel has read the invite unused and stops just before it writes.
    read_it, joined = threading.Event(), threading.Event()
    utc_now = team_service.utc_now

    def held_now():
        if threading.current_thread().name == "cancel":
            read_it.set()
            assert joined.wait(timeout=10)
        return utc_now()

    monkeypatch.setattr(team_service, "utc_now", held_now)
    outcome = {}

    def cancel():
        try:
            with session_factory.begin() as session:
                team_service.cancel_invite(session, admin, "acme", invite_id)
            outcome["cancel"] = "cancelled"
        except ValidationError as error:
            outcome["cancel"] = str(error)

    canceller = threading.Thread(target=cancel, name="cancel")
    canceller.start()
    assert read_it.wait(timeout=10)
    with session_factory.begin() as session:
        team_service.join_team(session, eve, code)
    joined.set()
    canceller.join(timeout=20)

    assert outcome["cancel"].startswith("That invite was already used")
    with session_factory() as session:
        invite = session.get(Invite, uuid.UUID(invite_id))
        assert invite.used_on is not None and invite.cancelled_on is None
        assert session.scalar(select(func.count()).select_from(TeamMember)
                              .where(TeamMember.user_id == eve)) == 2
