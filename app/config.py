from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _split_csv(value: str | None) -> list[str]:
    if not value:
        return []
    return [item.strip().lower() for item in value.split(",") if item.strip()]


def _as_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(slots=True)
class Settings:
    bot_token: str
    owner_id: int
    group_id: int | None
    news_thread_id: int | None
    db_path: Path
    telethon_enabled: bool
    min_text_length: int
    spam_limit_count: int
    spam_limit_minutes: int
    lock_ttl_minutes: int
    dedupe_days: int
    autopost_enabled: bool
    autopost_hour_limit: int
    auto_keywords: list[str]
    block_keywords: list[str]
    show_duplicates: bool
    notify_all_admins_about_autopost: bool

    @classmethod
    def from_env(cls) -> "Settings":
        group_raw = os.getenv("GROUP_ID")
        thread_raw = os.getenv("NEWS_THREAD_ID")

        return cls(
            bot_token=os.getenv("BOT_TOKEN", ""),
            owner_id=int(os.getenv("OWNER_ID", "0")),
            group_id=int(group_raw) if group_raw else None,
            news_thread_id=int(thread_raw) if thread_raw else None,
            db_path=Path(os.getenv("DB_PATH", "./data/bot.sqlite3")),
            telethon_enabled=_as_bool(os.getenv("TELETHON_ENABLED"), default=False),
            min_text_length=int(os.getenv("MIN_TEXT_LENGTH", "20")),
            spam_limit_count=int(os.getenv("SPAM_LIMIT_COUNT", "3")),
            spam_limit_minutes=int(os.getenv("SPAM_LIMIT_MINUTES", "30")),
            lock_ttl_minutes=int(os.getenv("LOCK_TTL_MINUTES", "30")),
            dedupe_days=int(os.getenv("DEDUPE_DAYS", "7")),
            autopost_enabled=_as_bool(os.getenv("AUTOPOST_ENABLED"), default=True),
            autopost_hour_limit=int(os.getenv("AUTOPOST_HOUR_LIMIT", "10")),
            auto_keywords=_split_csv(os.getenv("AUTO_KEYWORDS")),
            block_keywords=_split_csv(os.getenv("BLOCK_KEYWORDS")),
            show_duplicates=_as_bool(os.getenv("SHOW_DUPLICATES"), default=False),
            notify_all_admins_about_autopost=_as_bool(
                os.getenv("AUTOPOST_NOTIFY_ALL_ADMINS"), default=True
            ),
        )

    def validate(self) -> None:
        if not self.bot_token:
            raise ValueError("BOT_TOKEN is required")
        if self.owner_id <= 0:
            raise ValueError("OWNER_ID must be a positive integer")
