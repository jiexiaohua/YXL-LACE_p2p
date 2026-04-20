from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Dict, Protocol

PROTOCOL_VERSION = 1

TYPE_HELLO = "HELLO"
TYPE_HELLO_ACK = "HELLO_ACK"
TYPE_DATA = "DATA"
TYPE_ACK = "ACK"


@dataclass
class Packet:
    data: Dict[str, Any]


class PacketCodec(Protocol):
    def encode(self, packet: Packet) -> bytes:
        ...

    def decode(self, raw: bytes) -> Packet:
        ...


class JsonPacketCodec:
    def encode(self, packet: Packet) -> bytes:
        return json.dumps(packet.data, separators=(",", ":"), sort_keys=True).encode("utf-8")

    def decode(self, raw: bytes) -> Packet:
        parsed = json.loads(raw.decode("utf-8"))
        if not isinstance(parsed, dict):
            raise ValueError("packet must be a JSON object")
        return Packet(parsed)


def make_packet(packet_type: str, **kwargs: Any) -> Packet:
    payload = {"v": PROTOCOL_VERSION, "type": packet_type}
    payload.update(kwargs)
    return Packet(payload)


def stable_fields_for_mac(packet_data: Dict[str, Any]) -> bytes:
    mac_data = {k: v for k, v in packet_data.items() if k != "mac"}
    return json.dumps(mac_data, separators=(",", ":"), sort_keys=True).encode("utf-8")
