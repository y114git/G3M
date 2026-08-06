"""State machine for one game launch and its restoration lifecycle."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum


class LaunchState(StrEnum):
    IDLE = "idle"
    PREPARING = "preparing"
    RECOVERING = "recovering"
    BACKING_UP = "backing_up"
    APPLYING = "applying"
    DEPLOYED = "deployed"
    LAUNCHING = "launching"
    RUNNING = "running"
    RESTORING = "restoring"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    FAILED = "failed"


class LaunchTransitionError(RuntimeError):
    pass


_ALLOWED_TRANSITIONS: dict[LaunchState, set[LaunchState]] = {
    LaunchState.IDLE: {
        LaunchState.PREPARING,
        LaunchState.RECOVERING,
        LaunchState.FAILED,
    },
    LaunchState.PREPARING: {
        LaunchState.RECOVERING,
        LaunchState.BACKING_UP,
        LaunchState.LAUNCHING,
        LaunchState.CANCELLED,
        LaunchState.FAILED,
    },
    LaunchState.RECOVERING: {
        LaunchState.PREPARING,
        LaunchState.COMPLETED,
        LaunchState.FAILED,
    },
    LaunchState.BACKING_UP: {
        LaunchState.APPLYING,
        LaunchState.RESTORING,
        LaunchState.CANCELLED,
        LaunchState.FAILED,
    },
    LaunchState.APPLYING: {
        LaunchState.DEPLOYED,
        LaunchState.RESTORING,
        LaunchState.CANCELLED,
        LaunchState.FAILED,
    },
    LaunchState.DEPLOYED: {
        LaunchState.LAUNCHING,
        LaunchState.RESTORING,
        LaunchState.FAILED,
    },
    LaunchState.LAUNCHING: {
        LaunchState.RUNNING,
        LaunchState.RESTORING,
        LaunchState.FAILED,
    },
    LaunchState.RUNNING: {LaunchState.RESTORING, LaunchState.FAILED},
    LaunchState.RESTORING: {LaunchState.COMPLETED, LaunchState.FAILED},
    LaunchState.COMPLETED: {LaunchState.PREPARING, LaunchState.RECOVERING},
    LaunchState.CANCELLED: {
        LaunchState.PREPARING,
        LaunchState.RECOVERING,
        LaunchState.RESTORING,
    },
    LaunchState.FAILED: {
        LaunchState.PREPARING,
        LaunchState.RECOVERING,
        LaunchState.RESTORING,
    },
}


@dataclass
class LaunchTransaction:
    state: LaunchState = LaunchState.IDLE
    history: list[LaunchState] = field(default_factory=lambda: [LaunchState.IDLE])
    failure_reason: str | None = None

    def transition(self, state: LaunchState) -> None:
        if state == self.state:
            return
        if state not in _ALLOWED_TRANSITIONS[self.state]:
            raise LaunchTransitionError(
                f"Invalid launch transition: {self.state} -> {state}"
            )
        self.state = state
        self.history.append(state)

    def begin(self) -> None:
        self.failure_reason = None
        self.transition(LaunchState.PREPARING)

    def begin_apply(self) -> None:
        self.transition(LaunchState.BACKING_UP)
        self.transition(LaunchState.APPLYING)

    def mark_deployed(self, capture: Callable[[], bool]) -> bool:
        if not capture():
            self.fail("deployed-state")
            return False
        self.transition(LaunchState.DEPLOYED)
        return True

    def mark_launching(self) -> None:
        self.transition(LaunchState.LAUNCHING)

    def mark_running(self) -> None:
        self.transition(LaunchState.RUNNING)

    def restore(self, callback: Callable[[], bool]) -> bool:
        if self.state != LaunchState.RESTORING:
            self.transition(LaunchState.RESTORING)
        if callback():
            self.transition(LaunchState.COMPLETED)
            return True
        self.fail("restore")
        return False

    def recover(self, callback: Callable[[], bool]) -> bool:
        self.transition(LaunchState.RECOVERING)
        if callback():
            self.transition(LaunchState.COMPLETED)
            return True
        self.fail("recovery")
        return False

    def fail(self, reason: str) -> None:
        self.failure_reason = reason
        if self.state != LaunchState.FAILED:
            self.transition(LaunchState.FAILED)

    def snapshot(self) -> dict[str, object]:
        return {
            "state": self.state.value,
            "history": [state.value for state in self.history],
            "failure_reason": self.failure_reason,
        }
