"""Send VC Info link to a WeCom/WeChat interop group via WeCom PC UI automation.

This is a pragmatic fallback when external WeCom interop groups cannot use webhook bots
or AI bots. It requires WeCom PC to be installed and logged in on Windows.

Usage:
    python scripts/wecom_pc_rpa_send.py --group "VC Info 每日简报" --dry-run
    python scripts/wecom_pc_rpa_send.py --group "VC Info 每日简报"

Safety:
- Uses clipboard paste instead of typing, so Chinese text is reliable.
- Dry-run searches the group and pastes message into input box but does not press Enter.
- Keep WeCom logged in and avoid using mouse/keyboard while the script runs.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from datetime import datetime
from typing import Optional

import pyautogui
import pyperclip

try:
    import pygetwindow as gw
except Exception:  # pragma: no cover
    gw = None


pyautogui.FAILSAFE = True
pyautogui.PAUSE = 0.25


def build_link(date_str: Optional[str] = None) -> str:
    date_str = date_str or datetime.now().strftime("%Y-%m-%d")
    base_url = os.getenv("VCINFO_BASE_URL", "https://vcbrief.site").rstrip("/")
    return f"{base_url}/briefing/{date_str}"


def build_message(date_str: Optional[str] = None) -> str:
    link = build_link(date_str)
    return os.getenv(
        "VCINFO_RPA_MESSAGE",
        f"今日 VC Info 简报已更新：\n{link}\n\n关键词：AI / VC / 工具更新 / 投资相关资讯",
    )


def activate_wecom() -> bool:
    """Try to activate WeCom/企业微信 window."""
    if gw is None:
        return False

    keywords = ["企业微信", "WeCom", "WXWork"]
    windows = []
    for title in gw.getAllTitles():
        if title and any(k.lower() in title.lower() for k in keywords):
            windows.append(title)

    if not windows:
        return False

    win = gw.getWindowsWithTitle(windows[0])[0]
    try:
        if win.isMinimized:
            win.restore()
        win.activate()
        time.sleep(1)
        return True
    except Exception:
        return False


def paste_text(text: str) -> None:
    pyperclip.copy(text)
    time.sleep(0.2)
    pyautogui.hotkey("ctrl", "v")
    time.sleep(0.4)


def send_to_group(group_name: str, message: str, dry_run: bool = False, countdown: int = 3) -> None:
    print(f"[info] Target group: {group_name}")
    print(f"[info] Dry run: {dry_run}")
    print("[info] Do not use mouse/keyboard while running. Move mouse to top-left corner to abort.")
    for i in range(countdown, 0, -1):
        print(f"[info] Starting in {i}...")
        time.sleep(1)

    activated = activate_wecom()
    if not activated:
        print("[warn] Could not auto-activate WeCom window. Please click WeCom manually now.")
        time.sleep(3)

    # Search target group. WeCom usually supports Ctrl+F global search.
    pyautogui.hotkey("ctrl", "f")
    time.sleep(0.5)
    paste_text(group_name)
    time.sleep(1.0)
    pyautogui.press("enter")
    time.sleep(1.2)

    # Paste message into current chat input.
    paste_text(message)
    time.sleep(0.5)

    if dry_run:
        print("[dry-run] Message pasted but not sent. Check the target chat manually.")
        print("[dry-run] If target is correct, run again without --dry-run.")
        return

    pyautogui.press("enter")
    print("[ok] Send hotkey executed. Please verify the interop group received the message.")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--group", default=os.getenv("WECOM_RPA_GROUP", "VC Info 每日简报"))
    parser.add_argument("--date", default=os.getenv("VCINFO_DATE"))
    parser.add_argument("--message", default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--countdown", type=int, default=3)
    args = parser.parse_args()

    message = args.message or build_message(args.date)
    print("[preview]\n" + message)
    send_to_group(args.group, message, dry_run=args.dry_run, countdown=args.countdown)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
