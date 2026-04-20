from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Optional, Protocol, Set, Tuple

Addr = Tuple[str, int]


@dataclass
class Session:
    sid: str
    key: bytes
    send_seq: int = 0
    received_seqs: Set[int] = field(default_factory=set)


class SessionStore(Protocol):
    def get(self, addr: Addr) -> Optional[Session]:
        ...

    def set(self, addr: Addr, session: Session) -> None:
        ...


class InMemorySessionStore:
    def __init__(self) -> None:
        self._sessions: Dict[Addr, Session] = {}

    def get(self, addr: Addr) -> Optional[Session]:
        return self._sessions.get(addr)

    def set(self, addr: Addr, session: Session) -> None:
        self._sessions[addr] = session
