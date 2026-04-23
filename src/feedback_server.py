"""
Lightweight HTTP feedback server.
Receives feedback from Feishu card button clicks via URL redirect.

Usage: python feedback_server.py
Runs on port 9002 by default (configurable via FEEDBACK_PORT env var).
"""

import logging
import os
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

from feedback import FeedbackStore

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

store = FeedbackStore()


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
        title = params.get("t", [""])[0]

        if not item_id or reaction not in ("like", "dislike"):
            self._respond("参数错误", 400)
            return

        store.record(item_id, reaction, {"title": title, "channel": "", "domain": ""})
        emoji = "👍" if reaction == "like" else "👎"
        logger.info(f"Feedback: {emoji} for '{title[:40]}'")
        self._respond(f"{emoji} 已记录，感谢反馈！")

    def _respond(self, message: str, code: int = 200):
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        html = f"""<!DOCTYPE html><html><head><meta charset="utf-8">
        <meta name="viewport" content="width=device-width,initial-scale=1">
        <title>反馈</title></head><body style="display:flex;justify-content:center;
        align-items:center;height:100vh;font-size:24px;font-family:sans-serif;">
        {message}</body></html>"""
        self.wfile.write(html.encode("utf-8"))

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
