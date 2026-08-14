"""Tests for the game launch transaction state machine."""

import pytest

from services.launch_transaction import (
    LaunchState,
    LaunchTransaction,
    LaunchTransitionError,
)


def test_modded_launch_transaction_covers_full_lifecycle():
    transaction = LaunchTransaction()

    transaction.begin()
    transaction.begin_apply()
    assert transaction.mark_deployed(lambda: True)
    transaction.mark_launching()
    transaction.mark_running()
    assert transaction.restore(lambda: True)

    assert transaction.state == LaunchState.COMPLETED
    assert transaction.history == [
        LaunchState.IDLE,
        LaunchState.PREPARING,
        LaunchState.BACKING_UP,
        LaunchState.APPLYING,
        LaunchState.DEPLOYED,
        LaunchState.LAUNCHING,
        LaunchState.RUNNING,
        LaunchState.RESTORING,
        LaunchState.COMPLETED,
    ]


def test_vanilla_launch_skips_backup_and_apply_states():
    transaction = LaunchTransaction()

    transaction.begin()
    transaction.mark_launching()
    transaction.mark_running()
    assert transaction.restore(lambda: True)

    assert LaunchState.APPLYING not in transaction.history
    assert transaction.state == LaunchState.COMPLETED


def test_failed_deployed_state_stops_transaction():
    transaction = LaunchTransaction()
    transaction.begin()
    transaction.begin_apply()

    assert transaction.mark_deployed(lambda: False) is False
    assert transaction.state == LaunchState.FAILED
    assert transaction.failure_reason == "deployed-state"


def test_recovery_has_explicit_state_sequence():
    transaction = LaunchTransaction()

    assert transaction.recover(lambda: True)

    assert transaction.history == [
        LaunchState.IDLE,
        LaunchState.RECOVERING,
        LaunchState.COMPLETED,
    ]


@pytest.mark.parametrize(
    "state",
    [LaunchState.PREPARING, LaunchState.BACKING_UP, LaunchState.APPLYING],
)
def test_cancelled_launch_can_start_again(state):
    transaction = LaunchTransaction()
    transaction.begin()
    if state == LaunchState.BACKING_UP:
        transaction.transition(LaunchState.BACKING_UP)
    elif state == LaunchState.APPLYING:
        transaction.begin_apply()

    assert transaction.state == state
    transaction.cancel()
    assert transaction.state == LaunchState.CANCELLED
    transaction.begin()

    assert transaction.state == LaunchState.PREPARING


def test_invalid_transition_is_rejected():
    transaction = LaunchTransaction()

    with pytest.raises(LaunchTransitionError):
        transaction.mark_running()
