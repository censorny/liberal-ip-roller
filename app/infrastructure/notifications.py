import httpx
import logging
import asyncio
from typing import Optional
from storage.config_models import TelegramConfig
from app.core.events import bus, IpMatchEvent, WorkerErrorEvent

class TelegramNotifier:
    def __init__(self, config: TelegramConfig, report_matches: bool = True, report_errors: bool = True):
        self.config = config
        self.report_matches = report_matches
        self.report_errors = report_errors

    async def _send_message(self, text: str):
        if not self.config.enabled or not self.config.token or not self.config.chat_ids:
            return

        url = f"https://api.telegram.org/bot{self.config.token}/sendMessage"
        async with httpx.AsyncClient() as client:
            for chat_id in self.config.chat_ids:
                try:
                    await client.post(url, json={
                        "chat_id": chat_id,
                        "text": text,
                        "parse_mode": "HTML"
                    }, timeout=10.0)
                except Exception as e:
                    logging.error(f"Failed to send Telegram message to {chat_id}: {e}")

    async def on_match(self, event: IpMatchEvent):
        if self.report_matches:
            await self._send_message(f"✅ <b>Match Found!</b>\nIP: <code>{event.ip}</code>")

    async def on_error(self, event: WorkerErrorEvent):
        if self.report_errors:
            msg = event.error if hasattr(event, "error") else str(event)
            await self._send_message(f"❌ <b>Worker Error</b>\n<code>{msg}</code>")

_notifier: Optional[TelegramNotifier] = None

def setup_notifications(tg_config: TelegramConfig, report_matches: bool, report_errors: bool):
    global _notifier
    _notifier = TelegramNotifier(tg_config, report_matches, report_errors)

@bus.subscribe(IpMatchEvent)
async def _handle_ip_match(event: IpMatchEvent):
    if _notifier:
        await _notifier.on_match(event)

@bus.subscribe(WorkerErrorEvent)
async def _handle_worker_error(event: WorkerErrorEvent):
    if _notifier:
        await _notifier.on_error(event)
