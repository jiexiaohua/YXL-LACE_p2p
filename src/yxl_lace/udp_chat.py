from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import Tuple

from .crypto import aes_gcm_open, aes_gcm_seal
from .print import t

logger = logging.getLogger(__name__)

Addr = Tuple[str, int]

# UDP 单报文建议保持较小，避免 IP 分片导致丢包概率上升。
MAX_UDP_PLAIN = 1200
# AESGCM nonce(12) + tag(16) + 少量开销；这里只做粗略上限，主要限制明文长度。
MAX_UDP_BLOB = MAX_UDP_PLAIN + 64


class _UdpQueueProto(asyncio.DatagramProtocol):
    def __init__(self, queue: asyncio.Queue) -> None:
        self.queue = queue

    def datagram_received(self, data: bytes, addr: Addr) -> None:
        self.queue.put_nowait((data, addr))


async def udp_chat_loop_with_transport(
    *,
    session_key: bytes,
    peer_ip: str,
    peer_port: int,
    transport: asyncio.DatagramTransport,
    queue: asyncio.Queue,
) -> None:
    """
    UDP + AES-GCM 全双工聊天。

    - 复用握手阶段创建的 UDP transport（已绑定在本机默认端口上）。
    - 仅接受来自 (peer_ip, peer_port) 的报文，避免局域网噪声干扰。
    """
    peer: Addr = (peer_ip, peer_port)

    async def recv_task() -> None:
        try:
            while True:
                raw, addr = await queue.get()
                if addr != peer:
                    continue
                if not raw or len(raw) > MAX_UDP_BLOB:
                    continue
                try:
                    text = aes_gcm_open(session_key, raw).decode("utf-8", errors="replace")
                except Exception as exc:
                    logger.debug("udp decrypt failed from %s: %r", addr, exc)
                    continue
                print(f"\n[peer] {text}", flush=True)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.info("udp recv loop stopped: %r", exc)

    recv = asyncio.create_task(recv_task())
    try:
        sockname = transport.get_extra_info("sockname")
        local = f"{sockname[0]}:{sockname[1]}" if sockname else "0.0.0.0:?"
        print(
            t("chat_ready", local=local, peer_ip=peer_ip, peer_port=peer_port),
            flush=True,
        )
        while True:
            line = await asyncio.to_thread(input, "> ")
            line = line.rstrip("\n\r")
            if line == "/quit":
                break
            payload = line.encode("utf-8")
            if len(payload) > MAX_UDP_PLAIN:
                print(t("chat_msg_too_long", max_bytes=MAX_UDP_PLAIN), flush=True)
                continue
            blob = aes_gcm_seal(session_key, payload)
            transport.sendto(blob, peer)
    finally:
        recv.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await recv
        transport.close()


async def udp_chat_loop(
    *,
    session_key: bytes,
    local_port: int,
    peer_ip: str,
    peer_port: int,
) -> None:
    """兼容旧调用：单独创建 UDP transport 并聊天。"""
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue = asyncio.Queue()
    transport, _ = await loop.create_datagram_endpoint(
        lambda: _UdpQueueProto(queue),
        local_addr=("0.0.0.0", local_port),
    )
    try:
        await udp_chat_loop_with_transport(
            session_key=session_key,
            peer_ip=peer_ip,
            peer_port=peer_port,
            transport=transport,
            queue=queue,
        )
    finally:
        transport.close()
