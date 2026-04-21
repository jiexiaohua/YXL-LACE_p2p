from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from yxl_lace.relay_client import RelayChatClient  # noqa: E402


def prompt_non_empty(prompt: str) -> str:
    while True:
        value = input(prompt).strip()
        if value:
            return value
        print("输入不能为空。")


async def main() -> None:
    parser = argparse.ArgumentParser(description="YXL-LACE 中转聊天节点（交互模式）")
    parser.add_argument("--id", help="节点 ID，例如 alice")
    parser.add_argument("--psk", help="预共享密钥")
    parser.add_argument("--server", default="127.0.0.1:7000", help="中转服务器地址，默认 127.0.0.1:7000")
    parser.add_argument("--log-level", default="INFO", help="日志级别：DEBUG/INFO/WARNING")
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )

    cid = args.id or prompt_non_empty("节点ID> ")
    psk = args.psk or prompt_non_empty("预共享密钥PSK> ")

    host, port_text = args.server.split(":", 1)
    relay_host = host
    relay_port = int(port_text)

    client = RelayChatClient(client_id=cid, psk=psk, relay_host=relay_host, relay_port=relay_port)

    async def on_message(text: str, from_peer: str) -> None:
        print(f"\n[{from_peer}] {text}")

    client.set_message_handler(on_message)
    await client.start()

    current_peer: Optional[str] = None

    print("已连接中转服务器。")
    print("可用命令：/peer（设置/切换对象）、/leave（退出当前对象）、/quit（退出程序）")
    print("输入消息后回车发送。")

    try:
        while True:
            line = await asyncio.to_thread(input, "> ")
            line = line.strip()
            if not line:
                continue

            if line == "/quit":
                break

            if line == "/peer":
                peer_id = await asyncio.to_thread(prompt_non_empty, "对方节点ID> ")
                current_peer = peer_id
                print(f"当前聊天对象：{current_peer}")
                continue

            if line == "/leave":
                current_peer = None
                print("已退出当前聊天对象。")
                continue

            if current_peer is None:
                print("尚未设置聊天对象，请先输入 /peer")
                continue

            try:
                await client.send_text(current_peer, line)
            except Exception as exc:
                print(f"发送失败：{exc}")
    except (KeyboardInterrupt, EOFError):
        pass
    finally:
        await client.stop()


if __name__ == "__main__":
    asyncio.run(main())
