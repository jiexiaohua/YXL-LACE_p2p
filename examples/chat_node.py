from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path
from typing import Tuple

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from yxl_lace.peer import UdpPeer  # noqa: E402


def parse_addr(text: str) -> Tuple[str, int]:
    host, port = text.split(":", 1)
    return host, int(port)


async def main() -> None:
    parser = argparse.ArgumentParser(description="YXL-LACE UDP chat node")
    parser.add_argument("--id", required=True, help="peer id, e.g. alice")
    parser.add_argument("--bind", required=True, help="bind address, e.g. 127.0.0.1:9001")
    parser.add_argument("--peer", help="remote peer address, e.g. 127.0.0.1:9002")
    parser.add_argument("--psk", required=True, help="pre-shared key")
    parser.add_argument("--log-level", default="INFO", help="DEBUG/INFO/WARNING")
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )

    bind_host, bind_port = parse_addr(args.bind)
    peer = UdpPeer(peer_id=args.id, psk=args.psk, bind_host=bind_host, bind_port=bind_port)

    async def on_message(text: str, from_addr: Tuple[str, int]) -> None:
        print(f"\\n[{from_addr[0]}:{from_addr[1]}] {text}")

    peer.set_message_handler(on_message)
    await peer.start()

    remote_addr = parse_addr(args.peer) if args.peer else None
    if remote_addr:
        await peer.connect(remote_addr)

    print("Type messages and press Enter. Ctrl+C to quit.")
    try:
        while True:
            line = await asyncio.to_thread(input, "> ")
            if not line.strip():
                continue
            if not remote_addr:
                print("No peer set. Restart with --peer host:port")
                continue
            try:
                await peer.send_text(remote_addr, line)
            except Exception as exc:
                print(f"send failed: {exc}")
    except (KeyboardInterrupt, EOFError):
        pass
    finally:
        await peer.stop()


if __name__ == "__main__":
    asyncio.run(main())
