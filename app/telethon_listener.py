from __future__ import annotations

import asyncio
import contextlib
import json
import logging

from aiogram import Bot
from telethon import TelegramClient, events
from telethon.sessions import StringSession

from app.config import Settings
from app.db import Database, build_hash, now_iso

logger = logging.getLogger(__name__)


class TelethonListener:
    def __init__(self, settings: Settings, db: Database, bot: Bot):
        self.settings = settings
        self.db = db
        self.bot = bot
        self._tasks: list[asyncio.Task] = []

    async def start(self):
        if not self.settings.telethon_enabled:
            logger.info("Telethon listener disabled by TELETHON_ENABLED=0")
            return

        accounts = self.db.list_ready_enabled_accounts()
        if not accounts:
            logger.info("No READY+enabled telethon accounts")
            return

        for account in accounts:
            self._tasks.append(asyncio.create_task(self._run_account(account)))

        await asyncio.gather(*self._tasks, return_exceptions=True)

    async def _run_account(self, account):
        try:
            if not account["session_string"]:
                self.db.update_telethon_account_status(account["id"], "ERROR", "missing session")
                return
            client = TelegramClient(StringSession(account["session_string"]), int(account["api_id"]), account["api_hash"])
            await client.connect()
            if not await client.is_user_authorized():
                self.db.update_telethon_account_status(account["id"], "ERROR", "not authorized")
                await client.disconnect()
                return

            @client.on(events.NewMessage)
            async def on_new_message(event):
                await self._handle_message(account["id"], event)

            logger.info("Telethon account #%s started", account["id"])
            await client.run_until_disconnected()
        except Exception as exc:
            logger.exception("telethon account #%s crashed", account["id"])
            self.db.update_telethon_account_status(account["id"], "ERROR", str(exc))

    async def _handle_message(self, account_id: int, event):
        chat_identifier = str(event.chat_id)
        source = self.db.find_telethon_source(account_id, chat_identifier)
        if not source:
            return

        text = event.raw_text or ""
        media = []
        if event.photo:
            media.append({"type": "photo", "external_id": str(event.photo.id)})
        if event.video:
            media.append({"type": "video", "external_id": str(event.video.id)})
        if event.document:
            media.append({"type": "document", "external_id": str(event.document.id)})
        media_json = json.dumps(media, ensure_ascii=False)
        h = build_hash(text, media_json)

        if self.db.duplicate_exists(h, self.settings.dedupe_days):
            return

        if self._contains_any(text, json.loads(source["blacklist_keywords_json"] or "[]")):
            return

        if self._should_autopost(source, text):
            if self.settings.group_id and self.settings.news_thread_id:
                msg = await self.bot.send_message(self.settings.group_id, text, message_thread_id=self.settings.news_thread_id)
                nid = self.db.insert_news(
                    {
                        "source_type": "telethon",
                        "source_title": source["title"],
                        "source_link": self._build_link(event),
                        "source_chat_id": chat_identifier,
                        "author_user_id": None,
                        "author_username": None,
                        "text": text,
                        "media_json": media_json,
                        "status": "PUBLISHED",
                        "hash": h,
                        "published_message_id": msg.message_id,
                        "created_at": now_iso(),
                        "updated_at": now_iso(),
                    }
                )
                for admin in self.db.list_active_admins():
                    with contextlib.suppress(Exception):
                        await self.bot.send_message(admin["user_id"], f"⚡ Автопост: #{nid}")
                return

        news_id = self.db.insert_news(
            {
                "source_type": "telethon",
                "source_title": source["title"],
                "source_link": self._build_link(event),
                "source_chat_id": chat_identifier,
                "author_user_id": None,
                "author_username": None,
                "text": text,
                "media_json": media_json,
                "status": "PENDING",
                "hash": h,
                "created_at": now_iso(),
                "updated_at": now_iso(),
            }
        )
        for admin in self.db.list_active_admins():
            with contextlib.suppress(Exception):
                await self.bot.send_message(admin["user_id"], f"Нова новина з джерела {source['title']} #{news_id}")

    def _should_autopost(self, source, text: str) -> bool:
        if not bool(source["is_enabled"]):
            return False
        if not bool(source["allow_autopost"]):
            return False
        if source["autopost_mode"] != "KEYWORDS":
            return False
        return self._contains_any(text, json.loads(source["keywords_json"] or "[]"))

    @staticmethod
    def _contains_any(text: str, words: list[str]) -> bool:
        low = text.lower()
        return any(w.lower() in low for w in words if w)

    @staticmethod
    def _build_link(event) -> str | None:
        if getattr(event.chat, "username", None):
            return f"https://t.me/{event.chat.username}/{event.id}"
        return None
