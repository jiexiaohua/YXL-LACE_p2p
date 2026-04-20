from __future__ import annotations

import asyncio
import base64
import logging
from dataclasses import dataclass
from typing import Awaitable, Callable, Dict, Optional, Tuple

from .crypto import CryptoSuite, DefaultCryptoSuite
from .protocol import (
    PROTOCOL_VERSION,
    TYPE_ACK,
    TYPE_DATA,
    TYPE_HELLO,
    TYPE_HELLO_ACK,
    JsonPacketCodec,
    Packet,
    PacketCodec,
    make_packet,
    stable_fields_for_mac,
)
from .reliability import FixedRetryPolicy, RetryPolicy
from .session_store import InMemorySessionStore, Session, SessionStore

Addr = Tuple[str, int]
MessageHandler = Callable[[str, Addr], Awaitable[None]]


@dataclass
class PendingAck:
    event: asyncio.Event
    packet: Packet
    attempts: int = 0


class _DatagramHandler(asyncio.DatagramProtocol):
    def __init__(self, owner: "UdpPeer"):
        self.owner = owner

    def datagram_received(self, data: bytes, addr: Addr) -> None:
        self.owner.loop.create_task(self.owner._on_datagram(data, addr))

    def error_received(self, exc: Exception) -> None:
        self.owner.logger.error("udp error: %s", exc)


class UdpPeer:
    def __init__(
        self,
        peer_id: str,
        psk: str,
        bind_host: str,
        bind_port: int,
        *,
        codec: Optional[PacketCodec] = None,
        crypto_suite: Optional[CryptoSuite] = None,
        retry_policy: Optional[RetryPolicy] = None,
        session_store: Optional[SessionStore] = None,
        logger: Optional[logging.Logger] = None,
    ):
        self.peer_id = peer_id
        self.psk = psk
        self.bind_host = bind_host
        self.bind_port = bind_port

        self.codec = codec or JsonPacketCodec()
        self.crypto = crypto_suite or DefaultCryptoSuite()
        self.retry_policy = retry_policy or FixedRetryPolicy()
        self.session_store = session_store or InMemorySessionStore()

        self.logger = logger or logging.getLogger(f"yxl_lace.peer.{peer_id}")

        self.loop = asyncio.get_running_loop()
        self.transport: Optional[asyncio.DatagramTransport] = None
        self.client_nonces: Dict[Addr, str] = {}
        self.ready_events: Dict[Addr, asyncio.Event] = {}
        self.pending_acks: Dict[Addr, Dict[int, PendingAck]] = {}
        self.on_message: Optional[MessageHandler] = None

    async def start(self) -> None:
        transport, _ = await self.loop.create_datagram_endpoint(
            lambda: _DatagramHandler(self),
            local_addr=(self.bind_host, self.bind_port),
        )
        self.transport = transport
        self.logger.info("peer started on %s:%d", self.bind_host, self.bind_port)

    async def stop(self) -> None:
        if self.transport:
            self.transport.close()
            self.transport = None

    def set_message_handler(self, handler: MessageHandler) -> None:
        self.on_message = handler

    async def connect(self, addr: Addr, timeout: float = 5.0) -> None:
        if self._session_ready(addr):
            return

        client_nonce = self.crypto.random_nonce_hex()
        self.client_nonces[addr] = client_nonce
        self.ready_events.setdefault(addr, asyncio.Event())

        hello = make_packet(TYPE_HELLO, sender=self.peer_id, client_nonce=client_nonce)
        self._send_packet(hello, addr)

        self.logger.info("sent HELLO to %s", addr)
        await asyncio.wait_for(self.ready_events[addr].wait(), timeout=timeout)

    async def send_text(self, addr: Addr, text: str) -> None:
        if not self._session_ready(addr):
            await self.connect(addr)

        session = self.session_store.get(addr)
        if session is None:
            raise RuntimeError("session missing after connect")

        session.send_seq += 1
        seq = session.send_seq

        nonce = self.crypto.random_nonce_hex()
        cipher = self.crypto.encrypt_bytes(session.key, text.encode("utf-8"), nonce)
        data_packet = make_packet(
            TYPE_DATA,
            sid=session.sid,
            sender=self.peer_id,
            seq=seq,
            nonce=nonce,
            payload=base64.b64encode(cipher).decode("ascii"),
        )
        data_packet.data["mac"] = self.crypto.sign_packet(session.key, stable_fields_for_mac(data_packet.data))

        ack_event = asyncio.Event()
        self.pending_acks.setdefault(addr, {})[seq] = PendingAck(event=ack_event, packet=data_packet)
        await self._send_with_retry(addr, seq)

    async def _send_with_retry(self, addr: Addr, seq: int) -> None:
        pending = self.pending_acks[addr][seq]
        max_attempts = self.retry_policy.max_attempts()

        while pending.attempts < max_attempts:
            pending.attempts += 1
            self._send_packet(pending.packet, addr)
            self.logger.debug("send DATA seq=%d attempt=%d to %s", seq, pending.attempts, addr)

            timeout = self.retry_policy.timeout_for_attempt(pending.attempts)
            try:
                await asyncio.wait_for(pending.event.wait(), timeout=timeout)
                self.pending_acks.get(addr, {}).pop(seq, None)
                return
            except asyncio.TimeoutError:
                continue

        self.pending_acks.get(addr, {}).pop(seq, None)
        raise TimeoutError(f"message seq={seq} not acked by {addr}")

    async def _on_datagram(self, raw: bytes, addr: Addr) -> None:
        try:
            packet = self.codec.decode(raw)
        except Exception:
            self.logger.warning("drop invalid packet from %s", addr)
            return

        version = packet.data.get("v")
        if version != PROTOCOL_VERSION:
            self.logger.warning("drop packet with version=%s from %s", version, addr)
            return

        ptype = packet.data.get("type")
        if ptype == TYPE_HELLO:
            await self._handle_hello(packet, addr)
        elif ptype == TYPE_HELLO_ACK:
            await self._handle_hello_ack(packet, addr)
        elif ptype == TYPE_DATA:
            await self._handle_data(packet, addr)
        elif ptype == TYPE_ACK:
            await self._handle_ack(packet, addr)
        else:
            self.logger.warning("drop unknown packet type=%s from %s", ptype, addr)

    async def _handle_hello(self, packet: Packet, addr: Addr) -> None:
        client_nonce = packet.data.get("client_nonce")
        if not isinstance(client_nonce, str):
            return

        server_nonce = self.crypto.random_nonce_hex()
        sid = self.crypto.derive_session_id(client_nonce, server_nonce)
        key = self.crypto.derive_session_key(self.psk, client_nonce, server_nonce)

        self.session_store.set(addr, Session(sid=sid, key=key))
        self.ready_events.setdefault(addr, asyncio.Event()).set()

        hello_ack = make_packet(
            TYPE_HELLO_ACK,
            sender=self.peer_id,
            sid=sid,
            client_nonce=client_nonce,
            server_nonce=server_nonce,
        )
        self._send_packet(hello_ack, addr)
        self.logger.info("session established(passive) sid=%s from %s", sid, addr)

    async def _handle_hello_ack(self, packet: Packet, addr: Addr) -> None:
        client_nonce = packet.data.get("client_nonce")
        server_nonce = packet.data.get("server_nonce")
        sid = packet.data.get("sid")

        if not isinstance(client_nonce, str) or not isinstance(server_nonce, str) or not isinstance(sid, str):
            return

        expected_client_nonce = self.client_nonces.get(addr)
        if expected_client_nonce != client_nonce:
            self.logger.warning("unexpected HELLO_ACK from %s", addr)
            return

        key = self.crypto.derive_session_key(self.psk, client_nonce, server_nonce)
        self.session_store.set(addr, Session(sid=sid, key=key))
        self.ready_events.setdefault(addr, asyncio.Event()).set()
        self.logger.info("session established(active) sid=%s with %s", sid, addr)

    async def _handle_data(self, packet: Packet, addr: Addr) -> None:
        session = self.session_store.get(addr)
        if session is None:
            self.logger.warning("drop DATA without session from %s", addr)
            return

        sid = packet.data.get("sid")
        seq = packet.data.get("seq")
        nonce = packet.data.get("nonce")
        payload = packet.data.get("payload")
        mac = packet.data.get("mac")

        if sid != session.sid:
            self.logger.warning("drop DATA sid mismatch from %s", addr)
            return
        if not isinstance(seq, int) or not isinstance(nonce, str) or not isinstance(payload, str) or not isinstance(mac, str):
            return

        if not self.crypto.verify_packet_mac(session.key, stable_fields_for_mac(packet.data), mac):
            self.logger.warning("drop DATA mac fail from %s", addr)
            return

        ack = make_packet(TYPE_ACK, sender=self.peer_id, sid=session.sid, ack=seq)
        self._send_packet(ack, addr)

        if seq in session.received_seqs:
            return
        session.received_seqs.add(seq)

        try:
            ciphertext = base64.b64decode(payload.encode("ascii"))
            plaintext = self.crypto.decrypt_bytes(session.key, ciphertext, nonce).decode("utf-8")
        except Exception:
            self.logger.warning("drop DATA decrypt fail from %s", addr)
            return

        if self.on_message is not None:
            await self.on_message(plaintext, addr)

    async def _handle_ack(self, packet: Packet, addr: Addr) -> None:
        session = self.session_store.get(addr)
        if session is None:
            return

        sid = packet.data.get("sid")
        ack = packet.data.get("ack")
        if sid != session.sid or not isinstance(ack, int):
            return

        pending = self.pending_acks.get(addr, {}).get(ack)
        if pending:
            pending.event.set()

    def _session_ready(self, addr: Addr) -> bool:
        event = self.ready_events.get(addr)
        return self.session_store.get(addr) is not None and event is not None and event.is_set()

    def _send_packet(self, packet: Packet, addr: Addr) -> None:
        if self.transport is None:
            raise RuntimeError("peer is not started")
        self.transport.sendto(self.codec.encode(packet), addr)
