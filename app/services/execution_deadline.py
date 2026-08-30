"""Single semantic deadline shared by model, HTTP, task, and sandbox layers."""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass


class ExecutionDeadlineExceeded(TimeoutError):
    """Raised when the one user-visible task deadline has expired."""


@dataclass(frozen=True)
class ExecutionDeadline:
    execution_id: str
    expires_at_monotonic: float
    deadline_at_ms: int

    @classmethod
    def create(cls, timeout_seconds: float) -> "ExecutionDeadline":
        timeout_seconds = max(0.1, float(timeout_seconds))
        return cls(
            execution_id=uuid.uuid4().hex,
            expires_at_monotonic=time.monotonic() + timeout_seconds,
            deadline_at_ms=int((time.time() + timeout_seconds) * 1000),
        )

    def remaining_seconds(self) -> float:
        return max(0.0, self.expires_at_monotonic - time.monotonic())

    def require_remaining(self) -> float:
        remaining = self.remaining_seconds()
        if remaining <= 0:
            raise ExecutionDeadlineExceeded("任务已超过统一执行时限")
        return remaining
