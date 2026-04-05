"""
Telegram Notification Client for Liberal IP Roller.
Handles asynchronous message broadcasting to multiple chat IDs.
"""

import asyncio
import logging
from typing import List, Optional

import httpx


class TelegramClient:
    """
    A lightweight, asynchronous wrapper for the Telegram Bot API.
    Supports broadcasting messages to a list of subscribers.
    """

    def __init__(self, token: str = "", chat_ids: Optional[List[str]] = None):
        """
        Initializes the client with bot token and target chat IDs.
        
        Args:
            token: Telegram Bot token from @BotFather.
            chat_ids: List of numeric chat IDs to notify.
        """
        self.token = token
        self.chat_ids = chat_ids or []
        self._http_client: Optional[httpx.AsyncClient] = None
        self._init_client()

    def _init_client(self):
        """ Sets up the HTTP client with base URL if token is available. """
        if self.token:
            base_url = f"https://api.telegram.org/bot{self.token}"
            limits = httpx.Limits(
                max_connections=50,
                max_keepalive_connections=20
            )
            self._http_client = httpx.AsyncClient(
                timeout=10.0,
                base_url=base_url,
                limits=limits
            )
        else:
            self._http_client = None

    async def close(self):
        """ Cleanly closes the bot API connection pool. """
        if self._http_client:
            await self._http_client.aclose()
            self._http_client = None

    async def update_config(self, token: str, chat_ids: List[str]):
        """ Re-initializes the client with new credentials. """
        await self.close()
        self.token = token
        self.chat_ids = chat_ids
        self._init_client()

    async def send_message(self, text: str):
        """
        Broadcasts a message to all configured chat IDs concurrently.
        """
        if not self._http_client or not self.chat_ids:
            return

        tasks = []
        for chat_id in self.chat_ids:
            clean_id = chat_id.strip()
            if not clean_id:
                continue
            tasks.append(self._send_to_one(clean_id, text))

        if tasks:
            # We use gather to fire all notifications in parallel
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _send_to_one(self, chat_id: str, text: str):
        """ Sends a single message to one chat ID using HTML parse mode. """
        try:
            if not self._http_client:
                return
                
            response = await self._http_client.post(
                "/sendMessage",
                json={
                    "chat_id": chat_id,
                    "text": text,
                    "parse_mode": "HTML"
                }
            )
            response.raise_for_status()
        except Exception as e:
            logging.error(f"Telegram notification failed for {chat_id}: {e}")
