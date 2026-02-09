# Samar Hub News Bot

Production-oriented Telegram system for:
- aiogram moderation bot (`@SamarHubNewsBot`)
- Telethon source reader (user account)

## Features
- User news submission flow with anti-spam and preview.
- Moderation queue broadcast to admins in DM.
- Atomic claim/lock (`PENDING -> LOCKED`) with TTL support.
- Edit/reject/publish actions with audit log (`actions_log`).
- Publication to a required group topic via `message_thread_id`.
- Telethon ingestion from configured sources.
- Strict autopost policy: whitelist source + AUTO keywords + no BLOCK keywords.
- Deduplication by normalized hash over text/media signature.
- SQLite schema for news/admins/sources/users/settings/actions.
- Docker + docker-compose deployment.
- Logs are written to `logs/bot.log` (with rotation) and to stdout.

## Quick start
1. Copy env:
   ```bash
   cp .env.example .env
   ```
2. Fill required values:
   - `BOT_TOKEN`
   - `OWNER_ID`
   - `GROUP_ID`
   - `NEWS_THREAD_ID`
3. Run:
   ```bash
   docker compose up --build -d
   ```

## Owner notes
- Add source quickly via command in bot DM:
  - `/sources add <chat_identifier>`
- View status:
  - `/settings`
- Group/topic safety guard:
  - if `GROUP_ID` or `NEWS_THREAD_ID` is empty, publish is blocked and owner is notified.

## Commands
- User: `/start`, `/news` + button `🗂 Мої заявки/статус`
- Admin: `/queue`, `/mylocks`, кнопка `🛠 Адмін-панель`
- Owner: `/settings`, `/sources`, `/admin add|del|list`

## Admin panel
- Inline menu: акаунти Telethon, джерела, черга, автопост, статистика.
- Додавання Telethon акаунта виконується wizard-ом у ЛС (title -> api_id -> api_hash -> phone -> code -> 2FA).

## Important production caveats
- For full media album handling, add buffered media-group collector (current MVP stores first media units).
- Telethon initial authorization (code/2FA) must be completed on first run for session creation.
- Add backup/retention strategy for `data/bot.sqlite3` and session files.

## Telethon safe startup (Docker)
- By default, set `TELETHON_ENABLED=0` to run only aiogram bot.
- Enable listener only when Telethon auth is ready: `TELETHON_ENABLED=1`.
- Telethon акаунти додаються через адмін-панель wizard (API ID/HASH/phone/code/2FA).
- Listener never asks for phone/code via stdin in container. If session is not authorized, it logs an error and aiogram bot keeps running.


- User menu now includes working handlers for rules, contacting admins, and my status list.
