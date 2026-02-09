from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any

UTC = timezone.utc


def now_iso() -> str:
    return datetime.now(tz=UTC).isoformat()


def normalize_text(text: str) -> str:
    normalized = " ".join(text.lower().split())
    while "!!" in normalized:
        normalized = normalized.replace("!!", "!")
    while "??" in normalized:
        normalized = normalized.replace("??", "?")
    return normalized


def build_hash(text: str, media_signature: str) -> str:
    return sha256(f"{normalize_text(text)}|{media_signature}".encode("utf-8")).hexdigest()


class Database:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init()

    @contextmanager
    def conn(self):
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def _init(self) -> None:
        with self.conn() as c:
            c.executescript(
                """
CREATE TABLE IF NOT EXISTS news (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_type TEXT NOT NULL,
    source_title TEXT NOT NULL,
    source_link TEXT,
    source_chat_id TEXT,
    author_user_id INTEGER,
    author_username TEXT,
    text TEXT NOT NULL,
    media_json TEXT,
    status TEXT NOT NULL,
    locked_by_admin_id INTEGER,
    lock_expires_at TEXT,
    scheduled_at TEXT,
    hash TEXT NOT NULL,
    published_message_id INTEGER,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS admins (
    user_id INTEGER PRIMARY KEY,
    username TEXT,
    role TEXT NOT NULL,
    is_active INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS sources (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_identifier TEXT NOT NULL,
    title TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1,
    allow_autopost INTEGER NOT NULL DEFAULT 0,
    last_message_id INTEGER,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    username TEXT,
    is_banned INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS actions_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    news_id INTEGER NOT NULL,
    admin_id INTEGER,
    action TEXT NOT NULL,
    meta_json TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS drafts (
    draft_id TEXT PRIMARY KEY,
    author_user_id INTEGER NOT NULL,
    author_username TEXT,
    text TEXT NOT NULL,
    link TEXT,
    location TEXT,
    media_json TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS telethon_accounts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    phone TEXT NOT NULL,
    api_id INTEGER NOT NULL,
    api_hash TEXT NOT NULL,
    session_string TEXT,
    session_name TEXT,
    is_enabled INTEGER NOT NULL DEFAULT 1,
    status TEXT NOT NULL DEFAULT 'NEW',
    last_error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS telethon_sources (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id INTEGER NOT NULL,
    chat_identifier TEXT NOT NULL,
    title TEXT NOT NULL,
    type TEXT,
    is_enabled INTEGER NOT NULL DEFAULT 1,
    allow_autopost INTEGER NOT NULL DEFAULT 0,
    autopost_mode TEXT NOT NULL DEFAULT 'OFF',
    keywords_json TEXT,
    blacklist_keywords_json TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_news_status ON news(status);
CREATE INDEX IF NOT EXISTS idx_news_hash ON news(hash);
                """
            )
            self._migrate_news_columns(c)

    @staticmethod
    def _migrate_news_columns(c: sqlite3.Connection) -> None:
        cols = {row["name"] for row in c.execute("PRAGMA table_info(news)")}
        if "published_message_id" not in cols:
            c.execute("ALTER TABLE news ADD COLUMN published_message_id INTEGER")

    def ensure_owner(self, owner_id: int) -> None:
        with self.conn() as c:
            c.execute(
                "INSERT INTO admins(user_id, role, is_active) VALUES(?, 'owner', 1) ON CONFLICT(user_id) DO UPDATE SET role='owner', is_active=1",
                (owner_id,),
            )

    def add_admin(self, user_id: int, role: str = "admin") -> None:
        with self.conn() as c:
            c.execute(
                "INSERT INTO admins(user_id, role, is_active) VALUES(?, ?, 1) ON CONFLICT(user_id) DO UPDATE SET role=excluded.role, is_active=1",
                (user_id, role),
            )

    def deactivate_admin(self, user_id: int) -> None:
        with self.conn() as c:
            c.execute("UPDATE admins SET is_active=0 WHERE user_id=?", (user_id,))

    def add_user_if_missing(self, user_id: int, username: str | None) -> None:
        with self.conn() as c:
            c.execute(
                "INSERT OR IGNORE INTO users(user_id, username, is_banned, created_at) VALUES (?, ?, 0, ?)",
                (user_id, username, now_iso()),
            )

    def is_user_banned(self, user_id: int) -> bool:
        with self.conn() as c:
            row = c.execute("SELECT is_banned FROM users WHERE user_id=?", (user_id,)).fetchone()
            return bool(row and row["is_banned"])

    def user_recent_news_count(self, user_id: int, minutes: int) -> int:
        threshold = (datetime.now(tz=UTC) - timedelta(minutes=minutes)).isoformat()
        with self.conn() as c:
            row = c.execute(
                "SELECT COUNT(*) AS cnt FROM news WHERE source_type='user' AND author_user_id=? AND created_at>=?",
                (user_id, threshold),
            ).fetchone()
            return int(row["cnt"])

    def user_news(self, user_id: int, limit: int = 10) -> list[sqlite3.Row]:
        with self.conn() as c:
            return list(
                c.execute(
                    "SELECT * FROM news WHERE author_user_id=? ORDER BY id DESC LIMIT ?",
                    (user_id, limit),
                )
            )

    def cancel_pending_news_by_user(self, news_id: int, user_id: int) -> bool:
        with self.conn() as c:
            cur = c.execute(
                "UPDATE news SET status='CANCELED', updated_at=? WHERE id=? AND author_user_id=? AND status='PENDING'",
                (now_iso(), news_id, user_id),
            )
            return cur.rowcount == 1


    def save_draft(self, draft: dict[str, Any]) -> None:
        with self.conn() as c:
            c.execute(
                """
                INSERT INTO drafts(draft_id, author_user_id, author_username, text, link, location, media_json, created_at, updated_at)
                VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(draft_id) DO UPDATE SET
                  text=excluded.text,
                  link=excluded.link,
                  location=excluded.location,
                  media_json=excluded.media_json,
                  updated_at=excluded.updated_at
                """,
                (
                    draft["draft_id"],
                    draft["author_user_id"],
                    draft.get("author_username"),
                    draft["text"],
                    draft.get("link"),
                    draft.get("location"),
                    draft.get("media_json"),
                    draft["created_at"],
                    draft["updated_at"],
                ),
            )

    def get_draft(self, draft_id: str) -> sqlite3.Row | None:
        with self.conn() as c:
            return c.execute("SELECT * FROM drafts WHERE draft_id=?", (draft_id,)).fetchone()

    def delete_draft(self, draft_id: str) -> None:
        with self.conn() as c:
            c.execute("DELETE FROM drafts WHERE draft_id=?", (draft_id,))


    def create_telethon_account(self, title: str, phone: str, api_id: int, api_hash: str, status: str = "NEW") -> int:
        with self.conn() as c:
            cur = c.execute(
                """
                INSERT INTO telethon_accounts(title, phone, api_id, api_hash, is_enabled, status, created_at, updated_at)
                VALUES(?, ?, ?, ?, 1, ?, ?, ?)
                """,
                (title, phone, api_id, api_hash, status, now_iso(), now_iso()),
            )
            return int(cur.lastrowid)

    def update_telethon_account_status(self, account_id: int, status: str, last_error: str | None = None) -> None:
        with self.conn() as c:
            c.execute(
                "UPDATE telethon_accounts SET status=?, last_error=?, updated_at=? WHERE id=?",
                (status, last_error, now_iso(), account_id),
            )

    def save_telethon_session_string(self, account_id: int, session_string: str) -> None:
        with self.conn() as c:
            c.execute(
                "UPDATE telethon_accounts SET session_string=?, status='READY', last_error=NULL, updated_at=? WHERE id=?",
                (session_string, now_iso(), account_id),
            )

    def list_telethon_accounts(self) -> list[sqlite3.Row]:
        with self.conn() as c:
            return list(c.execute("SELECT * FROM telethon_accounts ORDER BY id DESC"))

    def get_telethon_account(self, account_id: int) -> sqlite3.Row | None:
        with self.conn() as c:
            return c.execute("SELECT * FROM telethon_accounts WHERE id=?", (account_id,)).fetchone()

    def set_telethon_account_enabled(self, account_id: int, enabled: bool) -> None:
        with self.conn() as c:
            c.execute(
                "UPDATE telethon_accounts SET is_enabled=?, status=CASE WHEN ? THEN status ELSE 'DISABLED' END, updated_at=? WHERE id=?",
                (1 if enabled else 0, 1 if enabled else 0, now_iso(), account_id),
            )

    def delete_telethon_account(self, account_id: int) -> None:
        with self.conn() as c:
            c.execute("DELETE FROM telethon_sources WHERE account_id=?", (account_id,))
            c.execute("DELETE FROM telethon_accounts WHERE id=?", (account_id,))

    def list_ready_enabled_accounts(self) -> list[sqlite3.Row]:
        with self.conn() as c:
            return list(c.execute("SELECT * FROM telethon_accounts WHERE is_enabled=1 AND status='READY'"))

    def create_telethon_source(self, account_id: int, chat_identifier: str, title: str, source_type: str = "channel") -> int:
        with self.conn() as c:
            cur = c.execute(
                """
                INSERT INTO telethon_sources(account_id, chat_identifier, title, type, is_enabled, allow_autopost, autopost_mode, keywords_json, blacklist_keywords_json, created_at, updated_at)
                VALUES(?, ?, ?, ?, 1, 0, 'OFF', '[]', '[]', ?, ?)
                """,
                (account_id, chat_identifier, title, source_type, now_iso(), now_iso()),
            )
            return int(cur.lastrowid)

    def list_telethon_sources(self, account_id: int | None = None) -> list[sqlite3.Row]:
        with self.conn() as c:
            if account_id is None:
                return list(c.execute("SELECT * FROM telethon_sources ORDER BY id DESC"))
            return list(c.execute("SELECT * FROM telethon_sources WHERE account_id=? ORDER BY id DESC", (account_id,)))

    def get_telethon_source(self, source_id: int) -> sqlite3.Row | None:
        with self.conn() as c:
            return c.execute("SELECT * FROM telethon_sources WHERE id=?", (source_id,)).fetchone()

    def update_telethon_source_flags(self, source_id: int, is_enabled: bool | None = None, allow_autopost: bool | None = None, autopost_mode: str | None = None) -> None:
        updates, vals = [], []
        if is_enabled is not None:
            updates.append("is_enabled=?")
            vals.append(1 if is_enabled else 0)
        if allow_autopost is not None:
            updates.append("allow_autopost=?")
            vals.append(1 if allow_autopost else 0)
        if autopost_mode is not None:
            updates.append("autopost_mode=?")
            vals.append(autopost_mode)
        if not updates:
            return
        vals.extend([now_iso(), source_id])
        with self.conn() as c:
            c.execute(f"UPDATE telethon_sources SET {', '.join(updates)}, updated_at=? WHERE id=?", tuple(vals))

    def set_telethon_source_keywords(self, source_id: int, keywords: list[str], blacklist: list[str]) -> None:
        with self.conn() as c:
            c.execute(
                "UPDATE telethon_sources SET keywords_json=?, blacklist_keywords_json=?, updated_at=? WHERE id=?",
                (json.dumps(keywords, ensure_ascii=False), json.dumps(blacklist, ensure_ascii=False), now_iso(), source_id),
            )

    def delete_telethon_source(self, source_id: int) -> None:
        with self.conn() as c:
            c.execute("DELETE FROM telethon_sources WHERE id=?", (source_id,))

    def find_telethon_source(self, account_id: int, chat_identifier: str) -> sqlite3.Row | None:
        with self.conn() as c:
            return c.execute(
                "SELECT * FROM telethon_sources WHERE account_id=? AND chat_identifier=? AND is_enabled=1",
                (account_id, chat_identifier),
            ).fetchone()

    def insert_news(self, payload: dict[str, Any]) -> int:
        keys = ", ".join(payload.keys())
        placeholders = ", ".join(["?"] * len(payload))
        with self.conn() as c:
            cursor = c.execute(
                f"INSERT INTO news ({keys}) VALUES ({placeholders})",
                tuple(payload.values()),
            )
            return int(cursor.lastrowid)

    def duplicate_exists(self, hash_value: str, days: int) -> bool:
        threshold = (datetime.now(tz=UTC) - timedelta(days=days)).isoformat()
        with self.conn() as c:
            row = c.execute(
                "SELECT 1 FROM news WHERE hash=? AND created_at>=? LIMIT 1",
                (hash_value, threshold),
            ).fetchone()
            return row is not None

    def list_active_admins(self) -> list[sqlite3.Row]:
        with self.conn() as c:
            return list(c.execute("SELECT * FROM admins WHERE is_active=1 ORDER BY role DESC, user_id"))

    def get_news(self, news_id: int) -> sqlite3.Row | None:
        with self.conn() as c:
            return c.execute("SELECT * FROM news WHERE id=?", (news_id,)).fetchone()

    def lock_news(self, news_id: int, admin_id: int, ttl_minutes: int) -> bool:
        expires = (datetime.now(tz=UTC) + timedelta(minutes=ttl_minutes)).isoformat()
        with self.conn() as c:
            cursor = c.execute(
                """
                UPDATE news
                SET status='LOCKED', locked_by_admin_id=?, lock_expires_at=?, updated_at=?
                WHERE id=?
                  AND (
                    status='PENDING'
                    OR (status='LOCKED' AND lock_expires_at IS NOT NULL AND lock_expires_at < ?)
                  )
                """,
                (admin_id, expires, now_iso(), news_id, now_iso()),
            )
            return cursor.rowcount == 1

    def update_news_status(self, news_id: int, status: str, admin_id: int | None = None) -> None:
        with self.conn() as c:
            c.execute(
                "UPDATE news SET status=?, locked_by_admin_id=?, updated_at=? WHERE id=?",
                (status, admin_id, now_iso(), news_id),
            )

    def mark_news_published(self, news_id: int, published_message_id: int) -> None:
        with self.conn() as c:
            c.execute(
                "UPDATE news SET status='PUBLISHED', published_message_id=?, updated_at=? WHERE id=?",
                (published_message_id, now_iso(), news_id),
            )

    def set_news_text(self, news_id: int, text: str) -> None:
        with self.conn() as c:
            c.execute("UPDATE news SET text=?, updated_at=? WHERE id=?", (text, now_iso(), news_id))

    def add_action(self, news_id: int, admin_id: int | None, action: str, meta: dict[str, Any] | None = None):
        with self.conn() as c:
            c.execute(
                "INSERT INTO actions_log(news_id, admin_id, action, meta_json, created_at) VALUES (?, ?, ?, ?, ?)",
                (news_id, admin_id, action, json.dumps(meta or {}, ensure_ascii=False), now_iso()),
            )

    def pending_counts(self) -> dict[str, int]:
        with self.conn() as c:
            row = c.execute(
                "SELECT SUM(CASE WHEN status='PENDING' THEN 1 ELSE 0 END) p, SUM(CASE WHEN status='LOCKED' THEN 1 ELSE 0 END) l FROM news"
            ).fetchone()
            return {"pending": int(row["p"] or 0), "locked": int(row["l"] or 0)}

    def enabled_sources_count(self) -> int:
        with self.conn() as c:
            row = c.execute("SELECT COUNT(*) cnt FROM sources WHERE enabled=1").fetchone()
            return int(row["cnt"])

    def add_source(self, chat_identifier: str, title: str) -> None:
        with self.conn() as c:
            c.execute(
                "INSERT INTO sources(chat_identifier, title, enabled, allow_autopost, created_at) VALUES(?, ?, 1, 0, ?)",
                (chat_identifier, title, now_iso()),
            )

    def list_sources(self) -> list[sqlite3.Row]:
        with self.conn() as c:
            return list(c.execute("SELECT * FROM sources ORDER BY id DESC"))

    def update_source_last_message(self, source_chat_identifier: str, message_id: int):
        with self.conn() as c:
            c.execute(
                "UPDATE sources SET last_message_id=? WHERE chat_identifier=?",
                (message_id, source_chat_identifier),
            )

    def find_source_by_identifier(self, source_chat_identifier: str) -> sqlite3.Row | None:
        with self.conn() as c:
            return c.execute(
                "SELECT * FROM sources WHERE chat_identifier=? AND enabled=1", (source_chat_identifier,)
            ).fetchone()

    def autopost_count_last_hour(self) -> int:
        threshold = (datetime.now(tz=UTC) - timedelta(hours=1)).isoformat()
        with self.conn() as c:
            row = c.execute(
                "SELECT COUNT(*) cnt FROM news WHERE status='PUBLISHED_AUTO' AND updated_at>=?", (threshold,)
            ).fetchone()
            return int(row["cnt"])
