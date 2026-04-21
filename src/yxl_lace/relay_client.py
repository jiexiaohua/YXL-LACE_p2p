from __future__ import annotations

import asyncio
import base64
import contextlib
import json
import logging
from dataclasses import dataclass, field
from typing import Awaitable, Callable, Dict, Optional, Set

from .crypto import DefaultCryptoSuite
from .protocol import (
    TYPE_ACK,
    TYPE_DATA,
    TYPE_HELLO,
    TYPE_HELLO_ACK,
    make_packet,
    stable_fields_for_mac,
)
from .reliability import FixedRetryPolicy, RetryPolicy

MessageHandler = Callable[[str, str], Awaitable[None]]


@dataclass
class PendingAck:
    event: asyncio.Event
    packet: dict
    attempts: int = 0


@dataclass
class Session:
    sid: str
    key: bytes
    send_seq: int = 0
    received_seqs: Set[int] = field(default_factory=set)
    ready: asyncio.Event = field(default_factory=asyncio.Event)


class RelayChatClient:
    def __init__(
        self,
        *,
        client_id: str,
        psk: str,
        relay_host: str,
        relay_port: int,
        connect_timeout: float = 30.0,
        retry_policy: Optional[RetryPolicy] = None,
        logger: Optional[logging.Logger] = None,
    ):
        self.client_id = client_id
        self.psk = psk
        self.relay_host = relay_host
        self.relay_port = relay_port
        self.connect_timeout = connect_timeout

        self.retry_policy = retry_policy or FixedRetryPolicy()
        self.crypto = DefaultCryptoSuite()
        self.logger = logger or logging.getLogger(f"yxl_lace.relay.client.{client_id}")

        self.reader: Optional[asyncio.StreamReader] = None
        self.writer: Optional[asyncio.StreamWriter] = None
        self.read_task: Optional[asyncio.Task] = None

        self.sessions: Dict[str, Session] = {}
        self.client_nonces: Dict[str, str] = {}
        self.pending_acks: Dict[str, Dict[int, PendingAck]] = {}
        self.on_message: Optional[MessageHandler] = None
        self._registered = asyncio.Event()

    def set_message_handler(self, handler: MessageHandler) -> None:
        self.on_message = handler

    async def start(self) -> None:
        self.reader, self.writer = await asyncio.open_connection(self.relay_host, self.relay_port)
        self.read_task = asyncio.create_task(self._read_loop())
        await self._send_control({"type": "REGISTER", "client_id": self.client_id})
        await asyncio.wait_for(self._registered.wait(), timeout=self.connect_timeout)

    async def stop(self) -> None:
        if self.read_task is not None:
            self.read_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self.read_task
            self.read_task = None

        if self.writer is not None:
            self.writer.close()
            await self.writer.wait_closed()
            self.writer = None

    async def set_peer(self, peer_id: str, timeout: Optional[float] = None) -> None:
        session = self.sessions.get(peer_id)
        if session and session.ready.is_set():
            return

        client_nonce = self.crypto.random_nonce_hex()
        self.client_nonces[peer_id] = client_nonce
        hello = make_packet(TYPE_HELLO, sender=self.client_id, client_nonce=client_nonce)
        await self._relay_send(peer_id, hello.data)

        if session is None:
            session = Session(sid="", key=b"")
            self.sessions[peer_id] = session

        await asyncio.wait_for(session.ready.wait(), timeout=timeout or self.connect_timeout)

    async def send_text(self, peer_id: str, text: str) -> None:
        await self.set_peer(peer_id)
        session = self.sessions[peer_id]

        session.send_seq += 1
        seq = session.send_seq

        nonce = self.crypto.random_nonce_hex()
        cipher = self.crypto.encrypt_bytes(session.key, text.encode("utf-8"), nonce)
        packet = make_packet(
            TYPE_DATA,
            sid=session.sid,
            sender=self.client_id,
            seq=seq,
            nonce=nonce,
            payload=base64.b64encode(cipher).decode("ascii"),
        ).data
        packet["mac"] = self.crypto.sign_packet(session.key, stable_fields_for_mac(packet))

        ack_event = asyncio.Event()
        self.pending_acks.setdefault(peer_id, {})[seq] = PendingAck(event=ack_event, packet=packet)
        await self._send_with_retry(peer_id, seq)

    async def _send_with_retry(self, peer_id: str, seq: int) -> None:
        pending = self.pending_acks[peer_id][seq]
        max_attempts = self.retry_policy.max_attempts()

        while pending.attempts < max_attempts:
            pending.attempts += 1
            await self._relay_send(peer_id, pending.packet)
            timeout = self.retry_policy.timeout_for_attempt(pending.attempts)

            try:
                await asyncio.wait_for(pending.event.wait(), timeout=timeout)
                self.pending_acks.get(peer_id, {}).pop(seq, None)
                return
            except asyncio.TimeoutError:
                continue

        self.pending_acks.get(peer_id, {}).pop(seq, None)
        raise TimeoutError(f"message seq={seq} not acked by {peer_id}")

    async def _read_loop(self) -> None:
        assert self.reader is not None
        while True:
            raw = await self.reader.readline()
            if not raw:
                raise ConnectionError("relay disconnected")
            msg = json.loads(raw.decode("utf-8"))
            await self._handle_control(msg)

    async def _handle_control(self, msg: dict) -> None:
        mtype = msg.get("type")
        if mtype == "REGISTERED":
            self._registered.set()
            return

        if mtype == "ERROR":
            reason = msg.get("reason")
            self.logger.warning("relay error: %s", reason)
            return

        if mtype == "RELAY":
            from_id = msg.get("from")
            packet = msg.get("packet")
            if isinstance(from_id, str) and isinstance(packet, dict):
                await self._handle_packet(from_id, packet)

    async def _handle_packet(self, from_id: str, packet: dict) -> None:
        ptype = packet.get("type")
        if ptype == TYPE_HELLO:
            await self._handle_hello(from_id, packet)
        elif ptype == TYPE_HELLO_ACK:
            await self._handle_hello_ack(from_id, packet)
        elif ptype == TYPE_DATA:
            await self._handle_data(from_id, packet)
        elif ptype == TYPE_ACK:
            await self._handle_ack(from_id, packet)

    async def _handle_hello(self, from_id: str, packet: dict) -> None:
        client_nonce = packet.get("client_nonce")
        if not isinstance(client_nonce, str):
            return

        server_nonce = self.crypto.random_nonce_hex()
        sid = self.crypto.derive_session_id(client_nonce, server_nonce)
        key = self.crypto.derive_session_key(self.psk, client_nonce, server_nonce)

        session = self.sessions.get(from_id)
        if session is None:
            session = Session(sid=sid, key=key)
            self.sessions[from_id] = session
        else:
            session.sid = sid
            session.key = key
        session.ready.set()

        hello_ack = make_packet(
            TYPE_HELLO_ACK,
            sender=self.client_id,
            sid=sid,
            client_nonce=client_nonce,
            server_nonce=server_nonce,
        ).data
        await self._relay_send(from_id, hello_ack)

    async def _handle_hello_ack(self, from_id: str, packet: dict) -> None:
        client_nonce = packet.get("client_nonce")
        server_nonce = packet.get("server_nonce")
        sid = packet.get("sid")

        if not isinstance(client_nonce, str) or not isinstance(server_nonce, str) or not isinstance(sid, str):
            return

        expected_nonce = self.client_nonces.get(from_id)
        if expected_nonce != client_nonce:
            return

        key = self.crypto.derive_session_key(self.psk, client_nonce, server_nonce)
        session = self.sessions.get(from_id)
        if session is None:
            session = Session(sid=sid, key=key)
            self.sessions[from_id] = session
        else:
            session.sid = sid
            session.key = key
        session.ready.set()

    async def _handle_data(self, from_id: str, packet: dict) -> None:
        session = self.sessions.get(from_id)
        if session is None or not session.ready.is_set():
            return

        sid = packet.get("sid")
        seq = packet.get("seq")
        nonce = packet.get("nonce")
        payload = packet.get("payload")
        mac = packet.get("mac")

        if sid != session.sid:
            return
        if not isinstance(seq, int) or not isinstance(nonce, str) or not isinstance(payload, str) or not isinstance(mac, str):
            return

        if not self.crypto.verify_packet_mac(session.key, stable_fields_for_mac(packet), mac):
            return

        ack = make_packet(TYPE_ACK, sender=self.client_id, sid=session.sid, ack=seq).data
        await self._relay_send(from_id, ack)

        if seq in session.received_seqs:
            return
        session.received_seqs.add(seq)

        ciphertext = base64.b64decode(payload.encode("ascii"))
        text = self.crypto.decrypt_bytes(session.key, ciphertext, nonce).decode("utf-8")

        if self.on_message is not None:
            await self.on_message(text, from_id)

    async def _handle_ack(self, from_id: str, packet: dict) -> None:
        session = self.sessions.get(from_id)
        if session is None:
            return

        sid = packet.get("sid")
        ack = packet.get("ack")
        if sid != session.sid or not isinstance(ack, int):
            return

        pending = self.pending_acks.get(from_id, {}).get(ack)
        if pending:
            pending.event.set()

    async def _relay_send(self, to_peer: str, packet: dict) -> None:
        await self._send_control({"type": "RELAY", "to": to_peer, "packet": packet})

    async def _send_control(self, payload: dict) -> None:
        if self.writer is None:
            raise RuntimeError("relay client not started")
        self.writer.write((json.dumps(payload, separators=(",", ":")) + "\n").encode("utf-8"))
        await self.writer.drain()
