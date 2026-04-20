from __future__ import annotations

import hashlib
import hmac
import secrets
from typing import Protocol


class CryptoSuite(Protocol):
    def derive_session_id(self, client_nonce: str, server_nonce: str) -> str:
        ...

    def derive_session_key(self, psk: str, client_nonce: str, server_nonce: str) -> bytes:
        ...

    def random_nonce_hex(self, size: int = 12) -> str:
        ...

    def encrypt_bytes(self, key: bytes, plaintext: bytes, nonce_hex: str) -> bytes:
        ...

    def decrypt_bytes(self, key: bytes, ciphertext: bytes, nonce_hex: str) -> bytes:
        ...

    def sign_packet(self, key: bytes, data_for_mac: bytes) -> str:
        ...

    def verify_packet_mac(self, key: bytes, data_for_mac: bytes, mac_hex: str) -> bool:
        ...


class DefaultCryptoSuite:
    def derive_session_id(self, client_nonce: str, server_nonce: str) -> str:
        return hashlib.blake2b((client_nonce + server_nonce).encode("utf-8"), digest_size=12).hexdigest()

    def derive_session_key(self, psk: str, client_nonce: str, server_nonce: str) -> bytes:
        material = f"{psk}|{client_nonce}|{server_nonce}".encode("utf-8")
        return hashlib.blake2b(material, digest_size=32).digest()

    def random_nonce_hex(self, size: int = 12) -> str:
        return secrets.token_hex(size)

    def _keystream(self, key: bytes, nonce_hex: str, length: int) -> bytes:
        out = bytearray()
        counter = 0
        nonce = bytes.fromhex(nonce_hex)
        while len(out) < length:
            counter_bytes = counter.to_bytes(4, "big")
            block = hashlib.blake2s(key + nonce + counter_bytes, digest_size=32).digest()
            out.extend(block)
            counter += 1
        return bytes(out[:length])

    def encrypt_bytes(self, key: bytes, plaintext: bytes, nonce_hex: str) -> bytes:
        stream = self._keystream(key, nonce_hex, len(plaintext))
        return bytes(a ^ b for a, b in zip(plaintext, stream))

    def decrypt_bytes(self, key: bytes, ciphertext: bytes, nonce_hex: str) -> bytes:
        return self.encrypt_bytes(key, ciphertext, nonce_hex)

    def sign_packet(self, key: bytes, data_for_mac: bytes) -> str:
        return hmac.new(key, data_for_mac, hashlib.sha256).hexdigest()

    def verify_packet_mac(self, key: bytes, data_for_mac: bytes, mac_hex: str) -> bool:
        expected = self.sign_packet(key, data_for_mac)
        return hmac.compare_digest(expected, mac_hex)
