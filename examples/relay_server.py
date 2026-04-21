from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from yxl_lace.relay_server import RelayServer  # noqa: E402


async def main() -> None:
    parser = argparse.ArgumentParser(description="YXL-LACE 中转服务器")
    parser.add_argument("--host", default="0.0.0.0", help="监听地址，默认 0.0.0.0")
    parser.add_argument("--port", type=int, default=7000, help="监听端口，默认 7000")
    parser.add_argument("--log-level", default="INFO", help="日志级别：DEBUG/INFO/WARNING")
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )

    server = RelayServer(host=args.host, port=args.port)
    await server.start()

    print(f"中转服务器已启动：{args.host}:{args.port}，按 Ctrl+C 退出")
    try:
        while True:
            await asyncio.sleep(3600)
    except KeyboardInterrupt:
        pass
    finally:
        await server.stop()


if __name__ == "__main__":
    asyncio.run(main())
