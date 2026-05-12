"""
Lightweight HTTP feedback server.
Receives feedback from Feishu card button clicks via URL redirect.
Supports optional comment submission after initial reaction.

Usage: python feedback_server.py
Runs on port 9002 by default (configurable via FEEDBACK_PORT env var).
"""

import html
import json
import logging
import os
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse, parse_qs, unquote

from feedback import FeedbackStore, BRIEFINGS_DIR

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

store = FeedbackStore()


def _find_item_in_briefings(item_id: str) -> dict:
    """Search recent briefing JSONs for item metadata by item_id."""
    json_files = sorted(BRIEFINGS_DIR.glob("briefing_*.json"), reverse=True)
    for jf in json_files[:7]:
        try:
            data = json.loads(jf.read_text(encoding="utf-8"))
            for item in data.get("items", []):
                if item.get("item_id") == item_id:
                    return item
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue
    return {}


class FeedbackHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path != "/feedback":
            self.send_response(404)
            self.end_headers()
            return

        params = parse_qs(parsed.query)
        item_id = params.get("id", [""])[0]
        reaction = params.get("r", [""])[0]

        if not item_id or reaction not in ("like", "dislike"):
            self._respond_html("参数错误：需要 id 和 r=like/dislike", 400)
            return

        # Look up full metadata from briefing JSON
        item_meta = _find_item_in_briefings(item_id)
        if not item_meta:
            item_meta = {"title": "(未找到简报元数据)", "item_id": item_id}
            logger.warning(f"Item {item_id} not found in briefings, recording minimal fallback")

        feedback_id = store.record(item_id, reaction, item_meta)
        emoji = "👍" if reaction == "like" else "👎"
        title_display = html.escape(item_meta.get("title", "")[:80])
        logger.info(f"Feedback: {emoji} for item_id={item_id[:12]}...")

        # Return page with optional comment form
        self._respond_html(f"""
            <div style="text-align:center;max-width:500px;margin:0 auto;">
                <h2>{emoji} 已记录，感谢反馈！</h2>
                <p style="color:#666;font-size:14px;">{title_display}</p>
                <hr style="margin:20px 0;">
                <p style="font-size:14px;color:#888;">想补充一句为什么？（可选）</p>
                <form method="POST" action="/feedback/comment">
                    <input type="hidden" name="feedback_id" value="{html.escape(feedback_id)}">
                    <textarea name="comment" rows="3"
                        style="width:100%;font-size:14px;padding:8px;border:1px solid #ddd;border-radius:6px;"
                        placeholder="例如：这类信息有投资决策价值 / 太偏营销了..."
                        maxlength="1000"></textarea>
                    <br><br>
                    <button type="submit"
                        style="padding:8px 24px;font-size:14px;background:#4f46e5;color:white;border:none;border-radius:6px;cursor:pointer;">
                        提交评语
                    </button>
                </form>
            </div>
        """)

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path != "/feedback/comment":
            self.send_response(404)
            self.end_headers()
            return

        content_length = int(self.headers.get("Content-Length", 0))
        if content_length > 5000:
            self._respond_html("请求过大", 400)
            return

        body = self.rfile.read(content_length).decode("utf-8")
        params = parse_qs(body)
        feedback_id = params.get("feedback_id", [""])[0].strip()[:100]
        comment = params.get("comment", [""])[0].strip()[:1000]

        if not feedback_id:
            self._respond_html("缺少 feedback_id", 400)
            return

        if not comment:
            self._respond_html("""
                <div style="text-align:center;margin-top:60px;">
                    <h2>👌 没有评语也没关系</h2>
                    <p style="color:#666;">你的反馈已经记录，下次简报会更贴近你的偏好。</p>
                </div>
            """)
            return

        success = store.update_comment(feedback_id, comment)
        if success:
            logger.info(f"Comment added for {feedback_id}: {comment[:40]}...")
            self._respond_html("""
                <div style="text-align:center;margin-top:60px;">
                    <h2>✅ 评语已保存</h2>
                    <p style="color:#666;">感谢补充，系统会学习你的偏好。</p>
                </div>
            """)
        else:
            self._respond_html("""
                <div style="text-align:center;margin-top:60px;">
                    <h2>⚠️ 未找到对应反馈记录</h2>
                    <p style="color:#666;">可能链接已过期，但你的初始反馈已保存。</p>
                </div>
            """)

    def _respond_html(self, body_content: str, code: int = 200):
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        page = f"""<!DOCTYPE html><html><head><meta charset="utf-8">
        <meta name="viewport" content="width=device-width,initial-scale=1">
        <title>反馈</title>
        <style>body{{display:flex;justify-content:center;align-items:center;min-height:100vh;font-family:-apple-system,sans-serif;padding:20px;}}</style>
        </head><body>{body_content}</body></html>"""
        self.wfile.write(page.encode("utf-8"))

    def log_message(self, format, *args):
        pass


def main():
    port = int(os.getenv("FEEDBACK_PORT", "9002"))
    server = HTTPServer(("0.0.0.0", port), FeedbackHandler)
    logger.info(f"Feedback server running on http://0.0.0.0:{port}")
    logger.info("Press Ctrl+C to stop")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("Server stopped")


if __name__ == "__main__":
    main()
