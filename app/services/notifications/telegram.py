import requests
from typing import Dict, Any, Optional

from app.services.base import BaseNotifier
from app.services.settings.service import SettingsResolver


class TelegramNotifier(BaseNotifier):
    def __init__(self, bot_token: str = "", chat_id: str = ""):
        self.bot_token = bot_token or SettingsResolver.get("telegram_bot_token", "")
        self.chat_id = chat_id or SettingsResolver.get("telegram_chat_id", "")
        self.base_url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"

    def send_notification(self, message: str, level: str = "INFO", context: Optional[Dict[str, Any]] = None) -> None:
        if not self.bot_token or not self.chat_id:
            return

        emoji_map = {
            "INFO": "i",
            "SUCCESS": "+",
            "WARNING": "!",
            "ERROR": "X",
            "CRITICAL": "!!"
        }

        emoji = emoji_map.get(level, "i")

        formatted_message = f"[{emoji}] Editorial Bot - {level}\n\n{message}"

        if context:
            formatted_message += "\n\nContext:"
            for k, v in context.items():
                formatted_message += f"\n- {k}: {v}"

        payload = {
            "chat_id": self.chat_id,
            "text": formatted_message,
        }

        try:
            response = requests.post(self.base_url, json=payload, timeout=10)
            response.raise_for_status()
        except requests.exceptions.RequestException:
            pass

notifier = TelegramNotifier()
