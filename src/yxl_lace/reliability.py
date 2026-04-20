from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


class RetryPolicy(Protocol):
    def max_attempts(self) -> int:
        ...

    def timeout_for_attempt(self, attempt_index: int) -> float:
        ...


@dataclass
class FixedRetryPolicy:
    timeout_seconds: float = 1.0
    retries: int = 5

    def max_attempts(self) -> int:
        return self.retries

    def timeout_for_attempt(self, attempt_index: int) -> float:
        return self.timeout_seconds
