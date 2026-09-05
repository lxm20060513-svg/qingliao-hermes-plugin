"""Qingliao platform adapter for Hermes Agent.

Bridges the Qingliao client into the Hermes agent loop. Inbound messages are
POSTed to a small HTTP endpoint (``/chat``); the adapter builds a
``MessageEvent``, hands it to the base ``handle_message`` (which spawns the
agent turn), and agent replies are written back to the Qingliao inbox via
``send()``.

This is a *plugin* (``kind: platform``) placed in the profile ``plugins/``
directory, so it survives image rebuilds of the floating ``latest`` tag.
"""

import asyncio
import json
import logging
import os
from datetime import datetime
from typing import Any, Dict, Optional

from gateway.config import Platform
from gateway.platforms.base import BasePlatformAdapter, MessageEvent, MessageType, SendResult

logger = logging.getLogger(__name__)

try:
    from aiohttp import web
    _HAS_AIOHTTP = True
except Exception:  # pragma: no cover - aiohttp is a Hermes dependency
    _HAS_AIOHTTP = False

_PLATFORM = "qingliao"


def _cfg(extra: Optional[dict], key: str, env: str, default: Optional[str] = None) -> Optional[str]:
    """Value from ``config.extra[key]`` (YAML) or ``os.environ[env]`` (env wins)."""
    v = None
    if extra:
        v = extra.get(key)
    if v is None:
        v = os.environ.get(env)
    return v if v is not None else default


class QingliaoAdapter(BasePlatformAdapter):

    def __init__(self, config, **kwargs):
        # Qingliao is a plugin-registered platform; its enum member may not exist yet
        # at adapter-construction time, so add it idempotently.
        try:
            platform = Platform(_PLATFORM)
        except ValueError:
            platform = Platform._add_pseudo_member(_PLATFORM)
        super().__init__(config=config, platform=platform)

        extra = getattr(config, "extra", {}) or {}
        self.port = int(_cfg(extra, "port", "QINGLIAO_PORT", 9130) or 9130)
        self.token = _cfg(extra, "token", "QINGLIAO_TOKEN", "") or ""
        self.out_dir = _cfg(extra, "out_dir", "QINGLIAO_OUT_DIR",
                            "./qingliao_out") or "./qingliao_out"
        allowed = (extra.get("allowed_users") or [])
        self.allowed_users = [str(u) for u in allowed]
        self._runner = None
        self._site = None

    @property
    def name(self) -> str:
        return "Qingliao"

    # ---- lifecycle ----

    async def connect(self, *, is_reconnect: bool = False) -> bool:
        if not _HAS_AIOHTTP:
            logger.error("qingliao: aiohttp not available")
            return False
        app = web.Application()
        app.router.add_get("/health", self._handle_health)
        app.router.add_post("/chat", self._handle_chat)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, host="0.0.0.0", port=self.port)
        await site.start()
        self._runner = runner
        self._site = site
        self._last_health = datetime.now().isoformat()
        logger.info("qingliao: HTTP listener up on port %s", self.port)
        return True

    async def disconnect(self) -> None:
        if self._site is not None:
            try:
                await self._site.stop()
            except Exception:
                pass
            self._site = None
        if self._runner is not None:
            try:
                await self._runner.cleanup()
            except Exception:
                pass
            self._runner = None

    # ---- outbound ----

    async def send(self, chat_id: str, content: str, reply_to: Optional[str] = None,
                   metadata: Optional[Dict[str, Any]] = None, **kwargs) -> SendResult:
        """Write the agent reply to the Qingliao inbox (HTTP push) + debug JSONL."""
        pushed = False
        try:
            await asyncio.to_thread(self._push_inbox, content)
            pushed = True
        except Exception as e:
            logger.warning("qingliao: inbox push failed: %s", e)
        # Debug trail: append to JSONL so the reply is inspectable even if push fails.
        try:
            os.makedirs(self.out_dir, exist_ok=True)
            rec = {
                "chat_id": str(chat_id),
                "ts": datetime.now().isoformat(),
                "content": content,
                "pushed": pushed,
            }
            path = os.path.join(self.out_dir, f"{chat_id}.jsonl")
            with open(path, "a", encoding="utf-8") as f:
                json.dump(rec, f, ensure_ascii=False)
                f.write("\n")
            return SendResult(success=True, message_id=None)
        except Exception as e:
            logger.warning("qingliao: send failed: %s", e)
            return SendResult(success=False, error=str(e))

    def _inbox_token(self) -> str:
        tok = os.environ.get("QL_INBOX_TOKEN", "")
        if tok:
            return tok.strip()
        tokf = os.environ.get("QL_INBOX_TOKEN_FILE", "./.inbox_token")
        try:
            with open(tokf, encoding="utf-8") as f:
                return f.read().strip()
        except Exception:
            return ""

    def _push_inbox(self, content: str) -> None:
        """Push the reply to the Qingliao inbox via the backend /api/inbox/push."""
        import urllib.request
        tok = self._inbox_token()
        if not host:
            raise RuntimeError("QL_HOST not set (Qingliao backend host)")
        host = os.environ.get("QL_HOST", "")
        port = os.environ.get("QL_INBOX_PORT", "9127")
        body = json.dumps({"text": content}, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            f"http://{host}:{port}/api/inbox/push", data=body, method="POST",
            headers={"Content-Type": "application/json", "X-Inbox-Token": tok})
        with urllib.request.urlopen(req, timeout=10) as r:
            r.read()

    def _dispatch(self, text: str, chat_id: str, user_id: str, user_name: str) -> None:
        """Build a MessageEvent and hand it to the base class handler."""
        if not self._message_handler:
            logger.warning("qingliao: no message handler wired; dropping message: %s", text[:60])
            return
        source = self.build_source(chat_id=chat_id, chat_name=chat_id, chat_type="dm",
                                   user_id=user_id, user_name=user_name)
        event = MessageEvent(
            text=text, message_type=MessageType.TEXT, source=source,
            message_id=datetime.now().strftime("%f"), timestamp=datetime.now(),
        )
        asyncio.create_task(self.handle_message(event))


# ---- module-level plugin hooks ----

def check_requirements() -> bool:
    return _HAS_AIOHTTP


def validate_config(config) -> bool:
    return True


def is_connected(config) -> bool:
    # Best-effort: the listener reports health at /health; here we just report configured.
    return bool(getattr(config, "extra", {}) or os.environ.get("QINGLIAO_PORT"))


def interactive_setup() -> None:
    logger.info("qingliao: no interactive setup required (token via env/config).")


def _env_enablement() -> Optional[Dict[str, Any]]:
    extra = {}
    if os.environ.get("QINGLIAO_PORT"):
        extra["port"] = int(os.environ["QINGLIAO_PORT"])
    if os.environ.get("QINGLIAO_TOKEN"):
        extra["token"] = os.environ["QINGLIAO_TOKEN"]
    return extra or None


def register(ctx) -> None:
    """Plugin entry point: called by the Hermes plugin system."""
    ctx.register_platform(
        name=_PLATFORM,
        label="Qingliao",
        adapter_factory=QingliaoAdapter,
        check_fn=check_requirements,
        validate_config=validate_config,
        required_env=["QINGLIAO_TOKEN"],
        install_hint="Needs aiohttp (Hermes standard dependency).",
        setup_fn=interactive_setup,
        env_enablement_fn=_env_enablement,
        cron_deliver_env_var="QINGLIAO_HOME_CHANNEL",
        allowed_users_env="QINGLIAO_ALLOWED_USERS",
        allow_all_env="QINGLIAO_ALLOW_ALL",
        emoji="💬",
        pii_safe=False,
        allow_update_command=True,
        platform_hint=(
            "You are chatting via Qingliao. Replies are delivered to the user through the "
            "Qingliao inbox. Keep responses concise and use Chinese."),
    )
