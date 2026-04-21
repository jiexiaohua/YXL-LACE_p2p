# YXL-LACE

一个 P2P、无中心化服务器的端到端加密项目，目标是通过去中心化加密保障信息安全（当前处于开发阶段）。

## 当前分支能力

- `main`：UDP 直连版（同网段/可直连网络优先）。
- `feature/server-relay`：服务器中转版（通过中转服务器实现跨网段通信）。

## 目录结构

- `docs/udp_transport_design.md`：UDP 传输层设计文档与演进路线。
- `docs/ui_integration_api.md`：UI 集成 API 详细文档。
- `docs/server_relay_design.md`：服务器中转版设计文档。
- `src/yxl_lace/peer.py`：UDP 节点核心（握手、ACK、重传、消息分发）。
- `src/yxl_lace/relay_server.py`：中转服务器实现。
- `src/yxl_lace/relay_client.py`：中转客户端 SDK。
- `examples/chat_node.py`：UDP 交互式聊天示例。
- `examples/relay_server.py`：中转服务器启动示例。
- `examples/relay_chat_node.py`：中转客户端交互示例。

## 中转版快速运行

1. 启动中转服务器：

```bash
python3 examples/relay_server.py --host 0.0.0.0 --port 7000
```

2. 启动客户端 A：

```bash
python3 examples/relay_chat_node.py --id alice --psk demo-key --server <服务器IP>:7000
```

3. 启动客户端 B：

```bash
python3 examples/relay_chat_node.py --id bob --psk demo-key --server <服务器IP>:7000
```

4. 在客户端内输入 `/peer`，设置对方节点 ID 后发送消息。

## 安全说明

当前默认密码实现用于开发联调，不可直接用于生产环境。
