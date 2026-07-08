"""Smoke test for WeCom AI Bot long-connection mode.

Purpose:
1. Connect with Bot ID / Secret.
2. Reply when the bot is mentioned in a group.
3. Persist discovered chat IDs for later proactive push tests.
4. Optionally send a proactive VC Info link to WECOM_TARGET_CHAT_ID.

Secrets must come from environment variables, not source code.
"""

from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from aibot import WSClient, WSClientOptions, generate_req_id

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
LOG_DIR = ROOT / "logs"
CHAT_FILE = DATA_DIR / "wecom_aibot_last_chat.json"


def today_link() -> str:
    date_str = os.getenv("VCINFO_DATE") or datetime.now().strftime("%Y-%m-%d")
    base_url = os.getenv("VCINFO_BASE_URL", "https://vcbrief.site").rstrip("/")
    return f"{base_url}/briefing/{date_str}"


def vcinfo_message() -> str:
    return os.getenv(
        "VCINFO_MESSAGE",
        f"今日 VC Info 简报已更新：\n{today_link()}\n\n关键词：AI / VC / 工具更新 / 投资相关资讯",
    )


def deep_get(obj: Any, paths: list[str]) -> Any:
    for path in paths:
        cur = obj
        ok = True
        for part in path.split("."):
            if isinstance(cur, dict) and part in cur:
                cur = cur[part]
            else:
                ok = False
                break
        if ok and cur:
            return cur
    return None


def extract_chat_id(frame: dict[str, Any]) -> str | None:
    """Try common locations because frame schema may vary by SDK/version."""
    value = deep_get(
        frame,
        [
            "body.chatid",
            "body.chat_id",
            "body.chat.chatid",
            "body.chat.chat_id",
            "body.conversation_id",
            "body.conversation.id",
            "chatid",
            "chat_id",
            "conversation_id",
        ],
    )
    return str(value) if value else None


def save_frame(frame: dict[str, Any], prefix: str) -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = LOG_DIR / f"{prefix}_{ts}.json"
    path.write_text(json.dumps(frame, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[log] saved frame: {path}")


def save_chat(frame: dict[str, Any], chat_id: str | None) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "saved_at": datetime.now().isoformat(timespec="seconds"),
        "chat_id": chat_id,
        "hint": "Set WECOM_TARGET_CHAT_ID to this chat_id for proactive push test.",
        "frame_excerpt": frame,
    }
    CHAT_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[chat] saved candidate chat id to: {CHAT_FILE}")
    print(f"[chat] candidate chat_id = {chat_id!r}")


async def main() -> None:
    load_dotenv(ROOT / ".env")
    bot_id = os.getenv("WECOM_BOT_ID") or os.getenv("WECHAT_BOT_ID")
    secret = os.getenv("WECOM_BOT_SECRET") or os.getenv("WECHAT_BOT_SECRET")
    target_chat_id = os.getenv("WECOM_TARGET_CHAT_ID")
    send_once = os.getenv("WECOM_SEND_ONCE", "0") == "1"

    if not bot_id or not secret:
        raise SystemExit(
            "Missing WECOM_BOT_ID / WECOM_BOT_SECRET. "
            "Set them in PowerShell env vars or local .env first."
        )

    client = WSClient(
        WSClientOptions(
            bot_id=bot_id,
            secret=secret,
            max_reconnect_attempts=-1,
        )
    )

    @client.on("authenticated")
    async def on_authenticated():
        print("[ok] WeCom AI Bot authenticated.")
        if send_once:
            if not target_chat_id:
                print("[warn] WECOM_SEND_ONCE=1 but WECOM_TARGET_CHAT_ID is empty.")
                print(f"[hint] First @ the bot in the target group, then read {CHAT_FILE}")
            else:
                print(f"[send] proactive push to chat_id={target_chat_id!r}")
                await client.send_message(
                    target_chat_id,
                    {
                        "msgtype": "markdown",
                        "markdown": {"content": vcinfo_message()},
                    },
                )
                print("[ok] proactive send attempted. Check the WeCom/WeChat group.")

    @client.on("message")
    async def on_any_message(frame):
        save_frame(frame, "wecom_message")
        chat_id = extract_chat_id(frame)
        save_chat(frame, chat_id)

    @client.on("message.text")
    async def on_text(frame):
        body = frame.get("body", {})
        content = deep_get(frame, ["body.text.content", "text.content"]) or ""
        chat_id = extract_chat_id(frame)
        print(f"[message.text] chat_id={chat_id!r}, content={content!r}")

        stream_id = generate_req_id("vcinfo")
        reply = (
            "今日 VC Info 简报入口：\n"
            f"{today_link()}\n\n"
            "如果你能在微信侧看到这条回复，说明智能机器人已能在互通群中响应。"
        )
        await client.reply_stream(frame, stream_id, reply, True)

    @client.on("event.enter_chat")
    async def on_enter_chat(frame):
        save_frame(frame, "wecom_enter_chat")
        chat_id = extract_chat_id(frame)
        save_chat(frame, chat_id)
        await client.reply_welcome(
            frame,
            {
                "msgtype": "text",
                "text": {
                    "content": (
                        "我是 VC Info Bot。\n"
                        "在群里 @我 并发送“今日简报”，我会返回当天 VC Info 链接。"
                    )
                },
            },
        )

    @client.on("error")
    def on_error(error):
        print(f"[error] {error}")

    print("[start] connecting WeCom AI Bot long connection...")
    await client.connect()
    await asyncio.Event().wait()


if __name__ == "__main__":
    asyncio.run(main())
