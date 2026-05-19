"""WeChat delivery via wxauto — send card image + text links to WeChat chat."""

import logging
import time
from pathlib import Path

logger = logging.getLogger(__name__)


class WechatDelivery:
    """Send briefing to WeChat via wxauto desktop automation."""

    def __init__(self, chat_name: str):
        self.chat_name = chat_name
        self._wx = None

    def _get_wx(self):
        if self._wx is None:
            from wxauto import WeChat
            self._wx = WeChat()
        return self._wx

    def send(
        self,
        card_image_path: Path,
        audio_url: str | None = None,
        detail_url: str | None = None,
    ) -> bool:
        """Send card image + links to the configured WeChat chat."""
        try:
            wx = self._get_wx()
            wx.ChatWith(self.chat_name)
            time.sleep(0.5)

            # Send the card image
            wx.SendFiles(str(card_image_path))
            time.sleep(1)

            # Send text with links
            lines = []
            if audio_url:
                lines.append(f"🎧 收听音频版\n{audio_url}")
            if detail_url:
                lines.append(f"📖 查看完整日报\n{detail_url}")

            if lines:
                wx.SendMsg("\n\n".join(lines))

            logger.info(f"WeChat delivery to '{self.chat_name}' succeeded")
            return True

        except ImportError:
            logger.error("wxauto not installed. Run: pip install wxauto")
            return False
        except Exception as e:
            logger.error(f"WeChat delivery failed: {e}")
            return False


# CLI test
if __name__ == "__main__":
    import sys

    if len(sys.argv) < 3:
        print("Usage: python wechat_delivery.py <chat_name> <image_path> [audio_url] [detail_url]")
        sys.exit(1)

    chat = sys.argv[1]
    img = Path(sys.argv[2])
    audio = sys.argv[3] if len(sys.argv) > 3 else None
    detail = sys.argv[4] if len(sys.argv) > 4 else None

    delivery = WechatDelivery(chat)
    ok = delivery.send(img, audio_url=audio, detail_url=detail)
    print("OK" if ok else "FAILED")
