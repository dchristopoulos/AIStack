import itertools

import pytest

from aistack.services.reconciliation import (
    Choice,
    Desired,
    Observed,
    Step,
    reconcile,
)

EVERY_PAIR = list(itertools.product(Desired, Observed))


def _choices(desired, observed) -> list[Choice]:
    return [option.choice for option in reconcile(desired, observed).options]


def _option(desired, observed, choice):
    return next(option for option in reconcile(desired, observed).options
                if option.choice is choice)


@pytest.mark.parametrize(("desired", "observed", "step"), [
    (Desired.ENABLED, Observed.ABSENT, Step.INSTALL),
    (Desired.ENABLED, Observed.CURRENT, Step.NOTHING),
    (Desired.ENABLED, Observed.STALE, Step.UPDATE),
    (Desired.ENABLED, Observed.UNKNOWN, Step.ASK),
    (Desired.DISABLED, Observed.ABSENT, Step.NOTHING),
    (Desired.DISABLED, Observed.CURRENT, Step.ASK),
    (Desired.DISABLED, Observed.STALE, Step.ASK),
    (Desired.DISABLED, Observed.UNKNOWN, Step.ASK),
    (Desired.UNDECIDED, Observed.ABSENT, Step.NOTHING),
    (Desired.UNDECIDED, Observed.CURRENT, Step.ASK),
    (Desired.UNDECIDED, Observed.STALE, Step.ASK),
    (Desired.UNDECIDED, Observed.UNKNOWN, Step.ASK),
])
def test_the_sync_contract_table(desired, observed, step):
    """All twelve rows of `docs/DESIGN.md` §4 The sync contract."""
    assert reconcile(desired, observed).step is step


def test_every_combination_has_a_verdict():
    assert len(EVERY_PAIR) == 12
    for desired, observed in EVERY_PAIR:
        assert reconcile(desired, observed).step in Step


@pytest.mark.parametrize(("desired", "observed"), EVERY_PAIR)
def test_sync_acts_silently_only_when_enabled_and_the_local_copy_is_known(desired, observed):
    """The one rule, stated as an invariant over the whole table (ADR-0006)."""
    step = reconcile(desired, observed).step

    if step in (Step.INSTALL, Step.UPDATE):
        assert desired is Desired.ENABLED
        assert observed in (Observed.ABSENT, Observed.STALE)


@pytest.mark.parametrize(("desired", "observed"), EVERY_PAIR)
def test_local_content_the_vault_does_not_have_is_never_touched_without_asking(desired,
                                                                             observed):
    if observed is Observed.UNKNOWN:
        assert reconcile(desired, observed).step is Step.ASK


@pytest.mark.parametrize(("desired", "observed"), EVERY_PAIR)
def test_nothing_absent_is_ever_asked_about(desired, observed):
    """Absent and not enabled is the no-op state: never installed, never reported."""
    if observed is Observed.ABSENT:
        assert reconcile(desired, observed).step in (Step.INSTALL, Step.NOTHING)
        assert reconcile(desired, observed).options == ()


@pytest.mark.parametrize(("desired", "observed"), EVERY_PAIR)
def test_only_a_question_carries_options(desired, observed):
    verdict = reconcile(desired, observed)

    assert bool(verdict.options) == (verdict.step is Step.ASK)


@pytest.mark.parametrize(("desired", "observed"), EVERY_PAIR)
def test_a_choice_loses_edits_only_when_there_are_edits_to_lose(desired, observed):
    for option in reconcile(desired, observed).options:
        if option.loses_local_edits:
            assert observed is Observed.UNKNOWN
            assert option.choice in (Choice.ENABLE, Choice.RESTORE, Choice.REMOVE)


@pytest.mark.parametrize(("desired", "observed"), EVERY_PAIR)
def test_every_destructive_choice_on_unknown_content_is_flagged(desired, observed):
    """The inverse: no way to overwrite or delete edited content behind an unflagged option."""
    if observed is not Observed.UNKNOWN:
        return
    for option in reconcile(desired, observed).options:
        if option.choice in (Choice.ENABLE, Choice.RESTORE, Choice.REMOVE):
            assert option.loses_local_edits is True


@pytest.mark.parametrize(("desired", "observed"), EVERY_PAIR)
def test_enabling_says_whether_it_rewrites_the_folder(desired, observed):
    """"Adopt?" alone is not informed consent when the files are about to change."""
    for option in reconcile(desired, observed).options:
        if option.choice is Choice.ENABLE:
            assert option.overwrites_local == (observed is not Observed.CURRENT)


@pytest.mark.parametrize(("desired", "observed"), EVERY_PAIR)
def test_a_skill_already_enabled_is_restored_and_never_enabled_again(desired, observed):
    """Enable changes what this machine manages. Restore only puts the vault's copy back."""
    choices = _choices(desired, observed)

    assert (Choice.RESTORE in choices) == (
        desired is Desired.ENABLED and observed is Observed.UNKNOWN)
    if desired is Desired.ENABLED:
        assert Choice.ENABLE not in choices
    for option in reconcile(desired, observed).options:
        if option.choice is Choice.RESTORE:
            assert option.overwrites_local and option.loses_local_edits


@pytest.mark.parametrize(("desired", "observed"), EVERY_PAIR)
def test_pushing_is_offered_exactly_when_the_local_copy_is_new_to_the_vault(desired, observed):
    assert (Choice.PUSH in _choices(desired, observed)) == (observed is Observed.UNKNOWN)


@pytest.mark.parametrize(("desired", "observed"), EVERY_PAIR)
def test_pushing_and_skipping_never_cost_anything(desired, observed):
    for option in reconcile(desired, observed).options:
        if option.choice in (Choice.PUSH, Choice.SKIP):
            assert not option.overwrites_local and not option.loses_local_edits


def test_removal_is_offered_only_where_the_user_already_said_no():
    """Remove means "finish what disable started". An undecided skill was never disabled."""
    for desired, observed in EVERY_PAIR:
        assert (Choice.REMOVE in _choices(desired, observed)) == (
            desired is Desired.DISABLED and observed is not Observed.ABSENT)


def test_the_options_for_each_question():
    assert _choices(Desired.ENABLED, Observed.UNKNOWN) == [
        Choice.RESTORE, Choice.PUSH, Choice.SKIP]
    assert _choices(Desired.DISABLED, Observed.CURRENT) == [Choice.ENABLE, Choice.REMOVE]
    assert _choices(Desired.DISABLED, Observed.STALE) == [Choice.ENABLE, Choice.REMOVE]
    assert _choices(Desired.DISABLED, Observed.UNKNOWN) == [
        Choice.PUSH, Choice.ENABLE, Choice.REMOVE, Choice.SKIP]
    assert _choices(Desired.UNDECIDED, Observed.CURRENT) == [Choice.ENABLE, Choice.SKIP]
    assert _choices(Desired.UNDECIDED, Observed.STALE) == [Choice.ENABLE, Choice.SKIP]
    assert _choices(Desired.UNDECIDED, Observed.UNKNOWN) == [
        Choice.PUSH, Choice.ENABLE, Choice.SKIP]


def test_removing_an_unmodified_copy_loses_nothing():
    assert _option(Desired.DISABLED, Observed.CURRENT, Choice.REMOVE).loses_local_edits is False
    assert _option(Desired.DISABLED, Observed.STALE, Choice.REMOVE).loses_local_edits is False
    assert _option(Desired.DISABLED, Observed.UNKNOWN, Choice.REMOVE).loses_local_edits is True
