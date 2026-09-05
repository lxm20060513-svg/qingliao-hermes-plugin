# Qingliao Platform Plugin for Hermes Agent

把 **Hermes Agent** 接进 **轻聊（Qingliao）App** 的官方平台插件。轻聊 App 的所有聊天（普通闲聊 + Agent 指令）经轻聊后端转发到本插件，进入 Hermes 的 **agent 循环**（工具调用 / 持久记忆 / 上下文管理），回复再写回轻聊收件箱让 App 轮询展示。

> 效果等价于微信 / QQ 通道：轻聊 App == Hermes agent 的一等客户端，而非"直连大模型的简单聊天"。

---

## 架构

```
┌──────────┐  POST /chat (Bearer QINGLIAO_TOKEN)   ┌─────────────────┐
│ 轻聊 App │ ────────────────────────────────────▶ │  QingliaoAdapter │
└──────────┘        {text, user_id, chat_id}       └────────┬────────┘
                                                            │ 注入 Hermes agent 循环
                                                            ▼
                                              （agent 工具 / 记忆 / 上下文）
                                                            │
                回复写回轻聊收件箱 ◀──── send() ──  ────────┘
                POST /api/inbox/push (X-Inbox-Token)
```

- **入站**：轻聊后端 `POST /chat` → 插件构建 `MessageEvent` → 交给 `handle_message()` 触发 agent turn。
- **出站**：agent 回复经 `send()` → 轻聊后端 `/api/inbox/push` 写收件箱 → App 轮询 `/api/inbox` 注入当前聊天会话。

## 特性

- **所有聊天恒走 Hermes agent**——Agent 智能回复开关、普通闲聊、Agent 指令统一进 agent 循环，与微信 / QQ 通道一致。
- **零核心改动**——插件方式（`kind: platform`），放在 profile 的 `plugins/` 用户级目录，抗 Hermes 镜像（浮动 `latest` tag）重建覆盖。
- **流式输出**——agent 回复经 Hermes 9123 SSE 增量写收件箱，App 按 `offset` 逐字流式渲染。
- **收件箱去重（taskId）**——推送带 `source_task_id`，App 比对最近流式任务 `taskId` 去重，根治「流式回复 + 收件箱推送」重复。

---

## 安装

插件放到 Hermes profile 的 `plugins/` 目录下（用户级目录，镜像重建不覆盖）：

```
<profile>/plugins/qingliao-platform/
├── plugin.yaml
└── qingliao_platform/
    ├── __init__.py
    └── adapter.py
```

> 用哪个 profile 就放到哪个 profile 的 `plugins/` 下。Hermes 插件发现机制会扫描该目录的 `plugin.yaml` 清单并调用 `register(ctx)` 注册平台。

注册后在 Hermes 配置（profile `config.yaml`）启用平台，并**重启 gateway**（s6 服务，如 `s6-svc -r /run/service/gateway-<profile>`）。

## 配置

配置经 Hermes 配置的 `platforms.qingliao.extra` 或环境变量（**环境变量优先级更高**）。

| 变量 | 必填 | 说明 |
|---|---|---|
| `QINGLIAO_TOKEN` | ✅ | 入站 `/chat` 的 Bearer token（轻聊后端需带上）。用 `password: true`，不落库。 |
| `QINGLIAO_PORT` | | 入站 HTTP 监听端口（默认 `9130`）。 |
| `QINGLIAO_HOME_CHANNEL` | | cron / 通知投递的默认 chat_id。 |
| `QINGLIAO_ALLOWED_USERS` | | 允许交互的 user_id 白名单（逗号分隔）；`*` 放行所有人。 |
| `QINGLIAO_ALLOW_ALL` | | truthy 开关放行所有人。 |
| `QL_HOST` | ✅ | 轻聊后端主机（收件箱推送目标，如轻聊后端的局域网地址）。 |
| `QL_INBOX_PORT` | | 收件箱推送端口（默认 `9127`）。 |
| `QL_INBOX_TOKEN_FILE` | | 收件箱推送 token 文件路径（默认 `./.inbox_token`，内容是 `X-Inbox-Token` 的值）。 |
| `QL_OUT_DIR` | | 调试 JSONL 落盘目录（默认 `./qingliao_out`）。 |

### config.yaml 示例

```yaml
platforms:
  qingliao:
    enabled: true
    extra:
      token: "<你的 QINGLIAO_TOKEN>"       # 或注入 env
      port: 9130
      allowed_users: ["*"]                  # 对接真实 uid 前的最简放行
```

### env 示例（也可注入）

```bash
export QINGLIAO_TOKEN="<你的 token>"
export QL_HOST="<轻聊后端主机>"
export QL_INBOX_PORT="9127"
```

---

## 轻聊后端对接

**入站**（轻聊后端 POST 到插件）：

```
POST http://<qingliao-host>:9130/chat
Authorization: Bearer <QINGLIAO_TOKEN>
Content-Type: application/json

{"text": "帮我查一下本机磁盘占用", "user_id": "u-test", "chat_id": "u-test"}
```

响应：`{"ok": true, "dispatched": true}` → 插件异步触发 agent，可立即返回。

**出站**（插件推送回复到轻聊后端收件箱）：

```
POST http://<QL_HOST>:<QL_INBOX_PORT>/api/inbox/push
X-Inbox-Token: <QL_INBOX_TOKEN_FILE 内容>
Content-Type: application/json

{"text": "<agent 回复全文>", "source_task_id": "<该轮 taskId>"}
```

App 每 5s 轮询 `/api/inbox`，拉到后注入当前会话（`shouldSkipDuplicate` 用 `source_task_id` 对最近流式 `taskId` 去重，避免重复展示）。

---

## 安全

- 所有 token（`QINGLIAO_TOKEN`、收件箱 `X-Inbox-Token`）走 **env / config**，源码不含任何密钥。
- 开源版已把本机默认值（主机 IP、本机路径）**全部参数化**为 env 变量，无敏感硬编码。
- `plugin.yaml` 中 `QINGLIAO_TOKEN` 标记 `password: true`，提示不落库。
- `.gitignore` 忽略收件箱 token 文件 / 调试目录 / `__pycache__`。

## FAQ

**为什么用插件而不是改 Hermes 核心？**
Hermes 官方镜像用浮动 `latest` tag，镜像层源码改动会被重建 / `pull` 覆盖。插件放在 profile 用户目录，构建在镜像之外，重建不丢。

**为什么不用 Hermes 的 native streaming？**
Hermes 原生流式基于"编辑已发送的那条消息"（需要 adapter 提供可追踪 `message_id`，如 Telegram / WeCom 能原地编辑原消息）。轻聊是转发型 adapter，没有"可编辑消息"概念，native streaming 会回退整段发送。正解是走 Hermes 9123 SSE（`delta.content` 增量写收件箱，App 按 `offset` 轮询流式渲染）。

**怎么确认插件起来了？**
`GET /health` 返回 `{"ok": true, "platform": "qingliao"}`，并查 gateway 日志中 `qingliao: HTTP listener up on port 9130`。

---

## 许可

MIT License（见 [LICENSE](LICENSE)）。
