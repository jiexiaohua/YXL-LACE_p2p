# YXL-LACE

A P2P, serverless, end-to-end encrypted project designed to ensure information security through decentralized encryption (currently under development).

## Current milestone: UDP transport layer

This repository now includes a first-pass UDP communication layer for encrypted chat experiments, with a strong focus on extensibility.

## Structure

- `docs/udp_transport_design.md`: UDP transport design and evolution plan.
- `src/yxl_lace/protocol.py`: packet models and pluggable packet codec.
- `src/yxl_lace/crypto.py`: pluggable crypto suite (default MVP implementation).
- `src/yxl_lace/reliability.py`: pluggable retry policy.
- `src/yxl_lace/session_store.py`: pluggable session storage.
- `src/yxl_lace/peer.py`: UDP peer runtime, handshake, ACK/retry, message delivery.
- `examples/chat_node.py`: interactive CLI demo.

## Quick start

Open two terminals:

Terminal A:

```bash
python3 examples/chat_node.py --id alice --bind 127.0.0.1:9001 --peer 127.0.0.1:9002 --psk demo-key
```

Terminal B:

```bash
python3 examples/chat_node.py --id bob --bind 127.0.0.1:9002 --peer 127.0.0.1:9001 --psk demo-key
```

Then type messages in either terminal.

## Extensibility points

- Replace `PacketCodec` for binary formats (e.g. protobuf/msgpack).
- Replace `CryptoSuite` with production handshake + AEAD implementations.
- Replace `RetryPolicy` for backoff/windowed reliability strategies.
- Replace `SessionStore` with persistent/distributed stores.

## Security note

The default cryptographic implementation is a development-stage placeholder for protocol bring-up and should not be used as-is in production.
