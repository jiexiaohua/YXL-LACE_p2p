# YXL-LACE UDP 传输层设计文档（可扩展版）

## 1. 目标与范围

本设计聚焦于端到端加密聊天系统的第一阶段：**UDP 网络通信层**，并以可扩展性为第一优先级。

本阶段目标：
- 在无中心服务器转发消息的前提下，实现 P2P UDP 消息收发。
- 在 UDP 不可靠的基础上，提供最小可靠性（ACK + 超时重传）。
- 通过组件化接口保证协议、加密、重传、存储都可独立替换。
- 提供可运行命令行节点，支持快速联调。

## 2. 架构原则

- 高内聚低耦合：每个模块只负责一类变化。
- 依赖倒置：`UdpPeer` 依赖抽象接口，而非具体实现。
- 插拔优先：默认实现可跑通，替换实现无需改核心流程。
- 渐进演进：先实现单链路稳定，再扩展到复杂网络条件。

## 3. 模块划分

- `protocol.py`
  - `Packet`：协议包对象
  - `PacketCodec`：编解码接口
  - `JsonPacketCodec`：默认 JSON 编解码
- `crypto.py`
  - `CryptoSuite`：加密套件接口
  - `DefaultCryptoSuite`：默认实现（开发验证）
- `reliability.py`
  - `RetryPolicy`：重传策略接口
  - `FixedRetryPolicy`：固定超时/固定重试次数
- `session_store.py`
  - `SessionStore`：会话存储接口
  - `InMemorySessionStore`：内存实现
- `peer.py`
  - `UdpPeer`：会话握手、收发、ACK、重传调度、上层回调

## 4. 协议（MVP）

消息类型：`HELLO / HELLO_ACK / DATA / ACK`

通用字段：
- `v`: 协议版本
- `type`: 消息类型
- `sender`: 发送端 ID

会话字段：
- `sid`: 会话 ID
- `client_nonce`, `server_nonce`: 握手随机数

数据字段：
- `seq`: 数据序号
- `ack`: 确认序号
- `nonce`: 数据随机数
- `payload`: Base64 密文
- `mac`: 完整性校验

## 5. 状态机

- 主动方：`INIT -> HELLO_SENT -> ESTABLISHED`
- 被动方：`INIT -> ESTABLISHED`

会话状态由 `SessionStore` 保存，`ready_events` 负责连接建立通知。

## 6. 可靠性机制

- 发送 `DATA(seq)` 后进入待确认集合。
- 若超时未收到 `ACK(seq)`，按 `RetryPolicy` 决定是否重发和超时参数。
- 当前默认：固定 1s 超时，最多 5 次发送尝试。

后续可扩展：
- 指数退避
- 累计 ACK
- 滑动窗口
- 拥塞控制

## 7. 加密与认证接口

`CryptoSuite` 提供：
- 会话 ID/会话密钥派生
- 数据加解密
- MAC 生成与验证
- 随机数生成

默认实现仅用于开发阶段。后续可替换为：
- `X25519 + HKDF`
- `AEAD (ChaCha20-Poly1305 / AES-GCM)`
- 双棘轮会话更新

## 8. 扩展策略

不改 `UdpPeer` 主流程即可替换：
- 协议序列化（JSON -> 二进制）
- 密码套件（PSK 模式 -> 真正 E2EE）
- 重传策略（固定重传 -> 动态网络自适应）
- 存储层（内存 -> 持久化/分布式）

## 9. 已知边界

- 未实现 NAT 穿透
- 未实现离线消息与会话恢复
- 未实现身份认证体系
- 默认密码实现不适合生产

## 10. 联调方式

通过 `examples/chat_node.py` 启动两个节点，本机回环地址验证互发、重传和会话建立。
