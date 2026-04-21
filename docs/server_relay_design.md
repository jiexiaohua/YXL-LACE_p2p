# YXL-LACE 服务器中转版设计文档（分支：feature/server-relay）

## 1. 目标

在保留客户端端到端加密处理的前提下，引入一个中转服务器，解决跨网段直连困难问题。

本版目标：
- 客户端通过 TCP 长连接接入中转服务器。
- 服务器仅按目标客户端 ID 转发，不解密业务消息。
- 客户端负责握手、加密、解密、MAC 校验、ACK。

## 2. 架构

- `relay_server.py`：中转服务器（注册与路由）。
- `relay_client.py`：中转客户端 SDK（握手、加解密、ACK 重传）。
- `examples/relay_server.py`：服务器启动示例。
- `examples/relay_chat_node.py`：客户端交互示例。

数据流：
1. 客户端 A/B 向服务器发送 `REGISTER`。
2. A 向 B 发送 `RELAY(packet)`。
3. 服务器包装来源后转发给 B。
4. B 在本地完成解密并发送 `ACK`（同样经服务器转发）。

## 3. 控制协议（客户端 <-> 服务器）

JSON Lines（每行一个 JSON）：

- 注册请求
```json
{"type":"REGISTER","client_id":"alice"}
```

- 注册成功
```json
{"type":"REGISTERED","client_id":"alice"}
```

- 转发请求
```json
{"type":"RELAY","to":"bob","packet":{...}}
```

- 转发下行
```json
{"type":"RELAY","from":"alice","packet":{...}}
```

- 错误
```json
{"type":"ERROR","reason":"target_offline"}
```

## 4. 安全边界

- 服务器只处理 envelope，不参与密钥协商与解密。
- 客户端间业务包继续使用 `HELLO/HELLO_ACK/DATA/ACK`。
- 默认密码套件仍是开发态实现，后续需替换为生产级算法。

## 5. 已实现范围

- 服务器多客户端注册与在线路由。
- 客户端按 `peer_id` 建立会话。
- 消息加密/MAC 校验/去重/ACK 重传。
- 交互式命令行示例支持切换聊天对象。

## 6. 快速运行

1. 启动服务器：
```bash
python3 examples/relay_server.py --host 0.0.0.0 --port 7000
```

2. 终端 A：
```bash
python3 examples/relay_chat_node.py --id alice --psk demo-key --server <服务器IP>:7000
```

3. 终端 B：
```bash
python3 examples/relay_chat_node.py --id bob --psk demo-key --server <服务器IP>:7000
```

4. 在 A/B 内输入 `/peer`，填写对方节点 ID（例如 `bob` 或 `alice`），然后发送消息。

## 7. 后续建议

- 服务端加鉴权（token/signature）。
- 服务端加离线消息队列。
- 支持多设备会话与消息历史同步。
- 引入正式 E2EE 协议（X25519 + HKDF + AEAD）。
