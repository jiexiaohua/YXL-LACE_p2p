from __future__ import annotations

import asyncio
import json
import logging
from typing import Dict, Optional


class RelayServer:
    """Simple TCP relay server.

    The server only routes envelopes by logical client_id and never decrypts payload.
    """

    def __init__(self, host: str = "0.0.0.0", port: int = 7000, *, logger: Optional[logging.Logger] = None):
        self.host = host
        self.port = port
        self.logger = logger or logging.getLogger("yxl_lace.relay.server")
        self._server: Optional[asyncio.AbstractServer] = None
        self._clients: Dict[str, asyncio.StreamWriter] = {}
        self._writers: Dict[asyncio.StreamWriter, str] = {}

    async def start(self) -> None:
        self._server = await asyncio.start_server(self._handle_client, self.host, self.port)
        self.logger.info("relay server listening on %s:%d", self.host, self.port)

    async def stop(self) -> None:
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None

        for writer in list(self._writers.keys()):
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass

        self._clients.clear()
        self._writers.clear()

    async def _handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        peername = writer.get_extra_info("peername")
        self.logger.info("client connected: %s", peername)

        try:
            while True:
                raw = await reader.readline()
                if not raw:
                    break

                try:
                    msg = json.loads(raw.decode("utf-8"))
                except Exception:
                    await self._send_json(writer, {"type": "ERROR", "reason": "invalid_json"})
                    continue

                mtype = msg.get("type")
                if mtype == "REGISTER":
                    await self._handle_register(msg, writer)
                elif mtype == "RELAY":
                    await self._handle_relay(msg, writer)
                else:
                    await self._send_json(writer, {"type": "ERROR", "reason": "unknown_type"})
        finally:
            cid = self._writers.pop(writer, None)
            if cid and self._clients.get(cid) is writer:
                self._clients.pop(cid, None)
                self.logger.info("client disconnected: %s", cid)
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass

    async def _handle_register(self, msg: dict, writer: asyncio.StreamWriter) -> None:
        client_id = msg.get("client_id")
        if not isinstance(client_id, str) or not client_id:
            await self._send_json(writer, {"type": "ERROR", "reason": "invalid_client_id"})
            return

        existing = self._clients.get(client_id)
        if existing is not None and existing is not writer:
            await self._send_json(writer, {"type": "ERROR", "reason": "client_id_taken"})
            return

        self._clients[client_id] = writer
        self._writers[writer] = client_id
        await self._send_json(writer, {"type": "REGISTERED", "client_id": client_id})
        self.logger.info("registered client: %s", client_id)

    async def _handle_relay(self, msg: dict, writer: asyncio.StreamWriter) -> None:
        from_id = self._writers.get(writer)
        to_id = msg.get("to")
        packet = msg.get("packet")

        if from_id is None:
            await self._send_json(writer, {"type": "ERROR", "reason": "not_registered"})
            return
        if not isinstance(to_id, str) or not to_id:
            await self._send_json(writer, {"type": "ERROR", "reason": "invalid_to"})
            return
        if not isinstance(packet, dict):
            await self._send_json(writer, {"type": "ERROR", "reason": "invalid_packet"})
            return

        target = self._clients.get(to_id)
        if target is None:
            await self._send_json(writer, {"type": "ERROR", "reason": "target_offline", "to": to_id})
            return

        await self._send_json(target, {"type": "RELAY", "from": from_id, "packet": packet})

    async def _send_json(self, writer: asyncio.StreamWriter, payload: dict) -> None:
        writer.write((json.dumps(payload, separators=(",", ":")) + "\n").encode("utf-8"))
        await writer.drain()
