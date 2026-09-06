# Qingliao Platform Plugin for Hermes Agent

把 **Qingliao（轻聊）App** 接入 Hermes Agent 的 **平台插件**。暴露一个 HTTP `/chat` 端点：
轻聊客户端把消息 POST 进来 → 本插件构建 `MessageEvent` 交给 **Hermes agent 循环** → agent 回复经 `send()` 写回轻聊收件箱。

> ⚠️ **边界**：本插件只承担「把消息注入 Hermes agent 循环」+「把回复写回轻聊收件箱」。完整链路里的
> 流式渲染、收件箱去重、"所有聊天恒走 agent" 均由 **轻聊后端（stream_api）+ 轻聊 App（InboxStore）**
> 实现，**不属于本插件**（详见下文"系统集成"）。本仓库开源的只有接入层的 `adapter.py`。

---

## 插件本身做什么（`adapter.py`）

- **入站**：`POST /chat` `{text, user_id, chat_id}` → 构建 `MessageEvent` → `handle_message()`（触发 Hermes agent turn，含工具 / 记忆 / 上下文）。
- **出站**：agent 回复 → `send()` → 轻聊后端收件箱 `/api/inbox/push`（`X-Inbox-Token`），**整段**写回，供 App 轮询。

> 插件**不**实现流式增量：回复经 `send()` 一次性整段推收件箱。逐字流式渲染是轻聊后端轮询 Hermes 9123 SSE、再由 App 按 `offset` 拉取实现的（见系统集成）。

## 系统集成（轻聊后端 + App 提供，非本插件）

| 能力 | 由谁实现 | 说明 |
|---|---|---|
| **流式渲染** | 轻聊后端 `_hermes_stream_worker` + App | 后端走 Hermes 9123 SSE，`delta.content` 增量写状态；App 按 `/api/stream/{taskId}?offset=N` 轮询逐字渲染 |
| **收件箱去重（taskId）** | 后端 `_maybe_push_app` + App `InboxStore` | 后端推收件箱带 `source_task_id`；App 比对最近流式任务 `taskId` 去重，根治「流式回复 + 收件箱推送」重复 |
| **所有聊天恒走 agent** | 轻聊后端 `_worker` | 后端不受"Agent 智能回复开关/指令/闲聊"之分，统一分流到 Hermes agent（平替微信/QQ 通道） |

## 架构（两种接入方式）

```
轻聊 App
   │
   ▼
轻聊后端（stream_api）
   │
   ├── (A) 通道式接入：POST /chat ──▶ 本插件(adapter) ──▶ Hermes agent 循环 ──send()──▶ 收件箱
   │
   └── (B) 直连式接入：Hermes 9123 SSE（后端 _hermes_stream_worker）──▶ 收件箱
```

- **(A) 走本插件**：把轻聊作为 Hermes 的**平台通道**（消息经 `/chat` 进 agent，回复整段写回收件箱）。
- **(B) 后端直连**：轻聊后端直接用 Hermes 9123（`/v1/chat/completions`），`_hermes_stream_worker` 消费 SSE 增量写状态 → App 流式渲染，完成后再经收件箱兜底。**(B) 是轻聊当前主链路**（支持流式 + taskId 去重）。

两者都能让轻聊消息进入 Hermes agent；本插件提供的是 (A) 通道式接入。

---

## 安装

**一键安装**（自动 clone 到目标目录、清掉 `.git`、并提示后续配置）：

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/lxm20060513-svg/qingliao-hermes-plugin/main/install.sh) <你的profile>/plugins/qingliao-platform
```

> curl 远程执行前建议先审阅 [`install.sh`](install.sh)（本仓库根目录）。也可 `git clone` 本仓库后本地运行 `bash install.sh <目标目录>`。

手动方式——插件放到 Hermes profile 的 `plugins/` 目录下（用户级目录，镜像重建不覆盖）：

```
<profile>/plugins/qingliao-platform/
├── plugin.yaml
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
| `QL_HOST` | ✅ | 轻聊后端主机（收件箱推送目标）。 |
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

## 轻聊后端对接（本插件侧）

**入站**（轻聊后端 POST 到插件）：

```
POST http://<qingliao-host>:9130/chat
Authorization: Bearer <QINGLIAO_TOKEN>
Content-Type: application/json

{"text": "帮我查一下本机磁盘占用", "user_id": "u-test", "chat_id": "u-test"}
```

响应：`{"ok": true, "dispatched": true}` → 插件异步触发 agent，可立即返回。

**出站**（插件推送回复到收件箱）：

```
POST http://<QL_HOST>:<QL_INBOX_PORT>/api/inbox/push
X-Inbox-Token: <QL_INBOX_TOKEN_FILE 内容>
Content-Type: application/json

{"text": "<agent 回复全文>"}
```

> 插件侧推送内容只有 `text`；`source_task_id`（taskId 去重用）由轻聊后端在 9123 直连路径里注入。App 也会配合去重逻辑避免「流式回复 + 收件箱推送」重复展示。

---

## 安全

- 所有 token（`QINGLIAO_TOKEN`、收件箱 `X-Inbox-Token`）走 **env / config**，源码不含任何密钥。
- 开源版已把本机默认值（主机 IP、本机路径、profile 名）**全部参数化 / 通用化**，无敏感硬编码。
- `plugin.yaml` 中 `QINGLIAO_TOKEN` 标记 `password: true`，提示不落库。
- `.gitignore` 忽略收件箱 token 文件 / 调试目录 / `__pycache__`。

## FAQ

**为什么用插件而不是改 Hermes 核心？**
Hermes 官方镜像用浮动 `latest` tag，镜像层源码改动会被重建 / `pull` 覆盖。插件放在 profile 用户目录，构建在镜像之外，重建不丢。

**为什么本插件没有流式 / taskId 去重？**
这两个是**轻聊后端 + App 侧**的能力：后端走 Hermes 9123 SSE 增量写状态实现流式、推送带 `source_task_id` 实现去重；本插件（通道式接入）只整段 `send()` 推收件箱。若要"流式 + 去重"，走轻聊后端直连 9123 的主链路（(B) 模式）。

**怎么确认插件起来了？**
`GET /health` 返回 `{"ok": true, "platform": "qingliao"}`，并查 gateway 日志中 `qingliao: HTTP listener up on port 9130`。

---

## 许可

MIT License（见 [LICENSE](LICENSE)）。
