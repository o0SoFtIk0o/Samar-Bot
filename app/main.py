from __future__ import annotations

import asyncio
import contextlib
import logging
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from dotenv import load_dotenv

from app.bot import BotApp
from app.config import Settings
from app.db import Database
from app.telethon_listener import TelethonListener

logger = logging.getLogger(__name__)


def configure_logging() -> None:
    log_handlers: list[logging.Handler] = [logging.StreamHandler()]
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    log_path = Path("logs") / f"bot_{ts}.log"

    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        if log_path.exists() and log_path.is_dir():
            raise IsADirectoryError(f"Log path is directory: {log_path}")
        log_handlers.append(
            RotatingFileHandler(log_path, maxBytes=1_000_000, backupCount=3, encoding="utf-8")
        )
    except OSError as exc:
        logging.getLogger(__name__).warning(
            "File logging disabled (%s). Using StreamHandler only.", exc
        )

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=log_handlers,
    )


async def run() -> None:
    load_dotenv()
    configure_logging()

    settings = Settings.from_env()
    settings.validate()

    db = Database(settings.db_path)
    db.ensure_owner(settings.owner_id)

    bot = Bot(token=settings.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    app = BotApp(settings=settings, db=db)
    dp = app.build_dispatcher()

    listener = TelethonListener(settings=settings, db=db, bot=bot)
    telethon_task = asyncio.create_task(listener.start())

    try:
        await dp.start_polling(bot)
    finally:
        if not telethon_task.done():
            telethon_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await telethon_task
        with contextlib.suppress(Exception):
            await bot.session.close()


if __name__ == "__main__":
    asyncio.run(run())
