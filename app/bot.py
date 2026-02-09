from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, ErrorEvent, Message
from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError
from telethon.sessions import StringSession

from app.config import Settings
from app.db import Database, build_hash, now_iso
from app.keyboards import (
    account_actions_keyboard,
    accounts_keyboard,
    admin_panel_button,
    admin_panel_keyboard,
    moderation_keyboard,
    my_news_keyboard,
    news_preview_keyboard,
    source_actions_keyboard,
    sources_keyboard,
    user_main_menu,
)

logger = logging.getLogger(__name__)
UTC = timezone.utc

RULES_TEXT = (
    "📌 Правила подачі новин\n\n"
    "1) Пишіть чітко: що, де, коли.\n"
    "2) Мінімум емоцій, максимум фактів.\n"
    "3) Не додавайте фейки/рекламу/спам.\n"
    "4) Фото/відео вітаються.\n"
    "5) Після перевірки новину можуть відредагувати перед публікацією."
)


class NewsForm(StatesGroup):
    text = State()
    media = State()
    link = State()
    location = State()
    edit_draft = State()
    edit_locked = State()
    contact_message = State()
    acc_title = State()
    acc_api_id = State()
    acc_api_hash = State()
    acc_phone = State()
    acc_code = State()
    acc_password = State()
    src_account_pick = State()
    src_chat = State()
    src_keywords = State()


@dataclass(slots=True)
class BotApp:
    settings: Settings
    db: Database

    def build_dispatcher(self) -> Dispatcher:
        dp = Dispatcher()

        @dp.callback_query()
        async def callback_logger(cb: CallbackQuery):
            logger.info("callback pressed user=%s data=%s", cb.from_user.id, cb.data)

        @dp.error()
        async def global_error(event: ErrorEvent):
            logger.exception("Unhandled update error: %s", event.exception)
            upd = event.update
            if getattr(upd, "callback_query", None):
                with contextlib.suppress(Exception):
                    await upd.callback_query.answer("Сталася помилка. Спробуйте ще раз", show_alert=True)
            elif getattr(upd, "message", None):
                with contextlib.suppress(Exception):
                    await upd.message.answer("Сталася помилка. Спробуйте ще раз")

        @dp.message(Command("start"))
        async def start(message: Message):
            self.db.add_user_if_missing(message.from_user.id, message.from_user.username)
            if self.db.is_user_banned(message.from_user.id):
                await message.answer("Ваш акаунт заблоковано.")
                return
            await message.answer("Вітаємо! Надішліть новину через меню.", reply_markup=user_main_menu())
            if self._is_admin(message.from_user.id):
                await message.answer("Доступна адмін-панель", reply_markup=admin_panel_button())

        @dp.message(F.text == "🛠 Адмін-панель")
        async def admin_panel_entry(message: Message):
            if not self._is_admin(message.from_user.id):
                return
            await message.answer("🛠 Адмін-панель", reply_markup=admin_panel_keyboard())

        @dp.callback_query(F.data.startswith("panel:"))
        async def panel_router(cb: CallbackQuery):
            if not self._is_admin(cb.from_user.id):
                await cb.answer("Немає доступу", show_alert=True)
                return
            action = cb.data.split(":", 1)[1]
            if action in {"root", "back"}:
                await cb.message.edit_text("🛠 Адмін-панель", reply_markup=admin_panel_keyboard())
            elif action == "accounts":
                rows = self.db.list_telethon_accounts()
                await cb.message.edit_text("👤 Telethon акаунти", reply_markup=accounts_keyboard(rows))
            elif action == "sources":
                rows = self.db.list_telethon_sources()
                await cb.message.edit_text("📡 Джерела", reply_markup=sources_keyboard(rows))
            elif action == "queue":
                c = self.db.pending_counts()
                await cb.message.answer(f"Черга: PENDING={c['pending']} LOCKED={c['locked']}")
            elif action == "autopost":
                await cb.message.answer("Налаштування автопосту доступні в картках джерел")
            elif action == "stats":
                await cb.message.answer(
                    f"accounts={len(self.db.list_telethon_accounts())} sources={len(self.db.list_telethon_sources())}"
                )
            await cb.answer()

        @dp.callback_query(F.data == "acc:add")
        async def acc_add_start(cb: CallbackQuery, state: FSMContext):
            if not self._is_admin(cb.from_user.id):
                await cb.answer("Немає доступу", show_alert=True)
                return
            await state.set_state(NewsForm.acc_title)
            await cb.message.answer("Введіть title акаунта")
            await cb.answer()

        @dp.message(NewsForm.acc_title)
        async def acc_title(message: Message, state: FSMContext):
            await state.update_data(acc_title=message.text)
            await state.set_state(NewsForm.acc_api_id)
            await message.answer("Введіть api_id")

        @dp.message(NewsForm.acc_api_id)
        async def acc_api_id(message: Message, state: FSMContext):
            try:
                api_id = int((message.text or "").strip())
            except ValueError:
                await message.answer("api_id має бути числом")
                return
            await state.update_data(acc_api_id=api_id)
            await state.set_state(NewsForm.acc_api_hash)
            await message.answer("Введіть api_hash")

        @dp.message(NewsForm.acc_api_hash)
        async def acc_api_hash(message: Message, state: FSMContext):
            await state.update_data(acc_api_hash=(message.text or "").strip())
            await state.set_state(NewsForm.acc_phone)
            await message.answer("Введіть phone у форматі +380...")

        @dp.message(NewsForm.acc_phone)
        async def acc_phone(message: Message, state: FSMContext):
            data = await state.get_data()
            phone = (message.text or "").strip()
            if not phone.startswith("+"):
                await message.answer("Невірний формат телефону. Приклад: +380...")
                return
            account_id = self.db.create_telethon_account(
                title=data["acc_title"], phone=phone, api_id=data["acc_api_id"], api_hash=data["acc_api_hash"], status="WAIT_CODE"
            )
            client = TelegramClient(StringSession(), data["acc_api_id"], data["acc_api_hash"])
            await client.connect()
            try:
                sent = await client.send_code_request(phone)
                await state.update_data(acc_id=account_id, acc_phone=phone, phone_code_hash=sent.phone_code_hash, temp_session=client.session.save())
                await state.set_state(NewsForm.acc_code)
                await message.answer("Введіть код з Telegram")
            except Exception as exc:
                self.db.update_telethon_account_status(account_id, "ERROR", str(exc))
                await message.answer(f"Помилка: {exc}")
                await state.clear()
            finally:
                await client.disconnect()

        @dp.message(NewsForm.acc_code)
        async def acc_code(message: Message, state: FSMContext):
            data = await state.get_data()
            client = TelegramClient(StringSession(data["temp_session"]), data["acc_api_id"], data["acc_api_hash"])
            await client.connect()
            try:
                code = re.sub(r"\D", "", (message.text or ""))
                await client.sign_in(phone=data["acc_phone"], code=code, phone_code_hash=data["phone_code_hash"])
                self.db.save_telethon_session_string(data["acc_id"], client.session.save())
                await message.answer("✅ Акаунт додано та авторизовано")
                await state.clear()
            except SessionPasswordNeededError:
                self.db.update_telethon_account_status(data["acc_id"], "WAIT_PASSWORD")
                await state.set_state(NewsForm.acc_password)
                await state.update_data(temp_session=client.session.save())
                await message.answer("Введіть 2FA пароль")
            except Exception as exc:
                self.db.update_telethon_account_status(data["acc_id"], "ERROR", str(exc))
                await message.answer(f"Помилка авторизації: {exc}")
                await state.clear()
            finally:
                await client.disconnect()

        @dp.message(NewsForm.acc_password)
        async def acc_password(message: Message, state: FSMContext):
            data = await state.get_data()
            client = TelegramClient(StringSession(data["temp_session"]), data["acc_api_id"], data["acc_api_hash"])
            await client.connect()
            try:
                pwd = (message.text or "").strip()
                if not pwd:
                    await message.answer("Пароль не може бути порожнім")
                    return
                await client.sign_in(password=pwd)
                self.db.save_telethon_session_string(data["acc_id"], client.session.save())
                await message.answer("✅ Акаунт додано та авторизовано")
            except Exception as exc:
                self.db.update_telethon_account_status(data["acc_id"], "ERROR", str(exc))
                await message.answer(f"Помилка 2FA: {exc}")
            finally:
                await client.disconnect()
                await state.clear()

        @dp.callback_query(F.data.startswith("acc:detail:"))
        async def acc_detail(cb: CallbackQuery):
            if not self._is_admin(cb.from_user.id):
                await cb.answer("Немає доступу", show_alert=True)
                return
            acc_id = int(cb.data.split(":")[2])
            acc = self.db.get_telethon_account(acc_id)
            if not acc:
                await cb.answer("Акаунт не знайдено", show_alert=True)
                return
            await cb.message.edit_text(
                f"#{acc['id']} {acc['title']}\nphone={acc['phone']}\nstatus={acc['status']}\nerror={acc['last_error'] or '-'}",
                reply_markup=account_actions_keyboard(acc_id, bool(acc["is_enabled"])),
            )
            await cb.answer()

        @dp.callback_query(F.data.startswith("acc:toggle:"))
        async def acc_toggle(cb: CallbackQuery):
            if self._role_of(cb.from_user.id) != "owner":
                await cb.answer("Лише owner", show_alert=True)
                return
            acc_id = int(cb.data.split(":")[2])
            acc = self.db.get_telethon_account(acc_id)
            if not acc:
                await cb.answer("Не знайдено", show_alert=True)
                return
            self.db.set_telethon_account_enabled(acc_id, not bool(acc["is_enabled"]))
            await cb.answer("Оновлено")

        @dp.callback_query(F.data.startswith("acc:check:"))
        async def acc_check(cb: CallbackQuery):
            acc_id = int(cb.data.split(":")[2])
            acc = self.db.get_telethon_account(acc_id)
            if not acc:
                await cb.answer("Не знайдено", show_alert=True)
                return
            try:
                client = TelegramClient(StringSession(acc["session_string"] or ""), int(acc["api_id"]), acc["api_hash"])
                await client.connect()
                ok = await client.is_user_authorized()
                await client.disconnect()
                self.db.update_telethon_account_status(acc_id, "READY" if ok else "ERROR", None if ok else "not authorized")
                await cb.answer("OK" if ok else "NOT AUTH", show_alert=not ok)
            except Exception as exc:
                self.db.update_telethon_account_status(acc_id, "ERROR", str(exc))
                await cb.answer("ERROR", show_alert=True)

        @dp.callback_query(F.data.startswith("acc:delete:"))
        async def acc_delete(cb: CallbackQuery):
            if self._role_of(cb.from_user.id) != "owner":
                await cb.answer("Лише owner", show_alert=True)
                return
            acc_id = int(cb.data.split(":")[2])
            self.db.delete_telethon_account(acc_id)
            await cb.answer("Видалено")

        @dp.callback_query(F.data == "src:add")
        async def src_add_start(cb: CallbackQuery, state: FSMContext):
            if not self._is_admin(cb.from_user.id):
                await cb.answer("Немає доступу", show_alert=True)
                return
            rows = self.db.list_telethon_accounts()
            if not rows:
                await cb.answer("Спочатку додайте акаунт", show_alert=True)
                return
            text = "Оберіть account_id та надішліть числом:\n" + "\n".join([f"{r['id']}: {r['title']}" for r in rows])
            await state.set_state(NewsForm.src_account_pick)
            await cb.message.answer(text)
            await cb.answer()

        @dp.message(NewsForm.src_account_pick)
        async def src_account_pick(message: Message, state: FSMContext):
            await state.update_data(src_account_id=int(message.text or "0"))
            await state.set_state(NewsForm.src_chat)
            await message.answer("Вставте chat_identifier (@name / id / link)")

        @dp.message(NewsForm.src_chat)
        async def src_chat(message: Message, state: FSMContext):
            data = await state.get_data()
            sid = self.db.create_telethon_source(data["src_account_id"], (message.text or "").strip(), (message.text or "").strip())
            await state.clear()
            await message.answer(f"✅ Джерело додано #{sid}")

        @dp.callback_query(F.data.startswith("src:detail:"))
        async def src_detail(cb: CallbackQuery):
            sid = int(cb.data.split(":")[2])
            src = self.db.get_telethon_source(sid)
            if not src:
                await cb.answer("Не знайдено", show_alert=True)
                return
            await cb.message.edit_text(
                f"#{src['id']} acc={src['account_id']}\n{src['title']} ({src['chat_identifier']})\nenabled={src['is_enabled']} autopost={src['allow_autopost']} mode={src['autopost_mode']}",
                reply_markup=source_actions_keyboard(sid, bool(src["is_enabled"]), bool(src["allow_autopost"]), src["autopost_mode"]),
            )
            await cb.answer()

        @dp.callback_query(F.data.startswith("src:toggle:"))
        async def src_toggle(cb: CallbackQuery):
            sid = int(cb.data.split(":")[2])
            src = self.db.get_telethon_source(sid)
            if not src:
                await cb.answer("Не знайдено", show_alert=True)
                return
            self.db.update_telethon_source_flags(sid, is_enabled=not bool(src["is_enabled"]))
            await cb.answer("Оновлено")

        @dp.callback_query(F.data.startswith("src:autopost:"))
        async def src_autopost(cb: CallbackQuery):
            sid = int(cb.data.split(":")[2])
            src = self.db.get_telethon_source(sid)
            if not src:
                await cb.answer("Не знайдено", show_alert=True)
                return
            self.db.update_telethon_source_flags(sid, allow_autopost=not bool(src["allow_autopost"]))
            await cb.answer("Оновлено")

        @dp.callback_query(F.data.startswith("src:mode:"))
        async def src_mode(cb: CallbackQuery):
            _, _, sid, mode = cb.data.split(":", 3)
            self.db.update_telethon_source_flags(int(sid), autopost_mode=mode)
            await cb.answer("Режим змінено")

        @dp.callback_query(F.data.startswith("src:delete:"))
        async def src_delete(cb: CallbackQuery):
            sid = int(cb.data.split(":")[2])
            self.db.delete_telethon_source(sid)
            await cb.answer("Видалено")

        # User + moderation
        @dp.message(F.text == "📌 Правила подачі")
        async def rules2(message: Message):
            await message.answer(RULES_TEXT)

        @dp.message(F.text == "☎️ Зв’язок з адмінами")
        async def contact_entry(message: Message, state: FSMContext):
            await state.set_state(NewsForm.contact_message)
            await message.answer("Напишіть ваше повідомлення для адмінів одним повідомленням.")

        @dp.message(NewsForm.contact_message)
        async def contact_send(message: Message, state: FSMContext):
            payload = f"📩 Повідомлення від користувача {message.from_user.full_name} ({message.from_user.id})\n\n{message.text or ''}"
            for admin in self.db.list_active_admins():
                try:
                    await message.bot.send_message(admin["user_id"], payload)
                except Exception:
                    await self._notify_owner_admin_unreachable(message.bot, str(admin["user_id"]))
            await state.clear()
            await message.answer("Ваше повідомлення передано адміністраторам ✅")

        @dp.message(Command("news"))
        @dp.message(F.text == "📰 Надіслати новину")
        async def news_entry(message: Message, state: FSMContext):
            if self.db.user_recent_news_count(message.from_user.id, self.settings.spam_limit_minutes) >= self.settings.spam_limit_count:
                await message.answer("Ви надсилаєте занадто часто…")
                return
            await state.clear()
            await state.set_state(NewsForm.text)
            await message.answer(f"Введіть текст новини (мінімум {self.settings.min_text_length} символів)")

        @dp.message(NewsForm.text)
        async def collect_text(message: Message, state: FSMContext):
            text = (message.text or "").strip()
            if len(text) < self.settings.min_text_length:
                await message.answer("Текст занадто короткий.")
                return
            await state.update_data(draft_id=str(uuid4()), text=text, media=[], link=None, location=None)
            await state.set_state(NewsForm.media)
            await message.answer("Додайте фото/відео (необов’язково) або напишіть 'пропустити'.")

        @dp.message(NewsForm.media)
        async def collect_media(message: Message, state: FSMContext):
            data = await state.get_data()
            media = data.get("media", [])
            if message.photo:
                media.append({"type": "photo", "file_id": message.photo[-1].file_id})
            elif message.video:
                media.append({"type": "video", "file_id": message.video.file_id})
            elif (message.text or "").lower() != "пропустити":
                await message.answer("Надішліть медіа або 'пропустити'.")
                return
            await state.update_data(media=media)
            await state.set_state(NewsForm.link)
            await message.answer("Додайте посилання/джерело (необов’язково) або 'пропустити'.")

        @dp.message(NewsForm.link)
        async def collect_link(message: Message, state: FSMContext):
            await state.update_data(link=None if (message.text or "").lower() == "пропустити" else message.text)
            await state.set_state(NewsForm.location)
            await message.answer("Вкажіть район/локацію (необов’язково) або 'пропустити'.")

        @dp.message(NewsForm.location)
        async def collect_location(message: Message, state: FSMContext):
            await state.update_data(location=None if (message.text or "").lower() == "пропустити" else message.text)
            await self._persist_and_show_preview(message, state)

        @dp.callback_query(F.data.startswith("draft:edit:"))
        async def draft_edit(cb: CallbackQuery, state: FSMContext):
            draft_id = cb.data.split(":", 2)[2]
            draft = self.db.get_draft(draft_id)
            if not draft or draft["author_user_id"] != cb.from_user.id:
                await cb.answer("Чернетка не знайдена або застаріла", show_alert=True)
                return
            await state.set_state(NewsForm.edit_draft)
            await state.update_data(draft_id=draft_id)
            await cb.answer()
            await cb.message.answer("✏️ Введіть новий текст новини")

        @dp.message(NewsForm.edit_draft)
        async def draft_edit_apply(message: Message, state: FSMContext):
            data = await state.get_data()
            draft = self.db.get_draft(data.get("draft_id", ""))
            if not draft:
                await state.clear()
                await message.answer("Чернетка не знайдена")
                return
            await state.update_data(text=message.text or "", media=json.loads(draft["media_json"] or "[]"), link=draft["link"], location=draft["location"])
            await state.set_state(NewsForm.location)
            await self._persist_and_show_preview(message, state)

        @dp.callback_query(F.data.startswith("draft:cancel:"))
        async def draft_cancel(cb: CallbackQuery, state: FSMContext):
            draft_id = cb.data.split(":", 2)[2]
            draft = self.db.get_draft(draft_id)
            if not draft or draft["author_user_id"] != cb.from_user.id:
                await cb.answer("Вже неактуально", show_alert=True)
                return
            self.db.delete_draft(draft_id)
            await state.clear()
            await cb.message.edit_reply_markup(reply_markup=None)
            await cb.message.answer("❌ Скасовано. Чернетку видалено.")
            await cb.answer()

        @dp.callback_query(F.data.startswith("draft:submit:"))
        async def draft_submit(cb: CallbackQuery, state: FSMContext):
            draft_id = cb.data.split(":", 2)[2]
            draft = self.db.get_draft(draft_id)
            if not draft or draft["author_user_id"] != cb.from_user.id:
                await cb.answer("Чернетка не знайдена або застаріла", show_alert=True)
                return
            media_json = draft["media_json"] or "[]"
            h = build_hash(draft["text"], media_json)
            if self.db.duplicate_exists(h, self.settings.dedupe_days):
                await cb.answer("Схоже, така новина вже надсилалась", show_alert=True)
                return
            nid = self.db.insert_news({
                "source_type": "user", "source_title": "user_submission", "source_link": draft["link"], "source_chat_id": str(cb.from_user.id),
                "author_user_id": cb.from_user.id, "author_username": cb.from_user.username, "text": self._with_location(draft["text"], draft["location"]),
                "media_json": media_json, "status": "PENDING", "hash": h, "created_at": now_iso(), "updated_at": now_iso()
            })
            self.db.delete_draft(draft_id)
            await state.clear()
            await cb.message.edit_reply_markup(reply_markup=None)
            sent = await self.broadcast_to_admins(cb.bot, nid)
            if sent == 0:
                await cb.message.answer("⚠️ Наразі немає активних модераторів. Заявка прийнята, але потребує налаштування.")
            await cb.message.answer("✅ Надіслано на модерацію. Дякуємо!")
            await cb.answer()

        @dp.callback_query(F.data.startswith("claim:"))
        async def claim(cb: CallbackQuery):
            nid = int(cb.data.split(":", 1)[1])
            if not self._is_admin(cb.from_user.id):
                await cb.answer("Немає доступу", show_alert=True)
                return
            ok = self.db.lock_news(nid, cb.from_user.id, self.settings.lock_ttl_minutes)
            news = self.db.get_news(nid)
            if not news:
                await cb.answer("Не знайдено", show_alert=True)
                return
            if not ok:
                await cb.answer("Вже взято іншим", show_alert=True)
                return
            await cb.message.answer(f"Новина #{nid} закріплена", reply_markup=moderation_keyboard(nid, news['source_link']))
            await cb.answer()

        @dp.callback_query(F.data.startswith("publish:"))
        async def publish(cb: CallbackQuery):
            nid = int(cb.data.split(":", 1)[1])
            news = self.db.get_news(nid)
            if not news or not self._can_moderate(cb.from_user.id, news):
                await cb.answer("Немає прав", show_alert=True)
                return
            if not self.settings.group_id or not self.settings.news_thread_id:
                await self.notify_owner_missing_target(cb.bot)
                await cb.answer("Публікація заблокована", show_alert=True)
                return
            msg = await cb.bot.send_message(self.settings.group_id, news["text"], message_thread_id=self.settings.news_thread_id)
            self.db.mark_news_published(nid, msg.message_id)
            if news["author_user_id"]:
                with contextlib.suppress(Exception):
                    await cb.bot.send_message(news["author_user_id"], "Вашу новину опубліковано ✅")
            await cb.answer("Опубліковано")

        @dp.callback_query(F.data.startswith("reject:"))
        async def reject(cb: CallbackQuery):
            nid = int(cb.data.split(":", 1)[1])
            news = self.db.get_news(nid)
            if not news or not self._can_moderate(cb.from_user.id, news):
                await cb.answer("Немає прав", show_alert=True)
                return
            self.db.update_news_status(nid, "REJECTED")
            if news["author_user_id"]:
                with contextlib.suppress(Exception):
                    await cb.bot.send_message(news["author_user_id"], "Вашу новину відхилено ❌")
            await cb.answer("Відхилено")

        @dp.callback_query(F.data.startswith("unlock:"))
        async def unlock(cb: CallbackQuery):
            nid = int(cb.data.split(":", 1)[1])
            news = self.db.get_news(nid)
            if not news:
                await cb.answer("Не знайдено", show_alert=True)
                return
            if self._role_of(cb.from_user.id) != "owner" and news["locked_by_admin_id"] != cb.from_user.id:
                await cb.answer("Немає прав", show_alert=True)
                return
            self.db.update_news_status(nid, "PENDING", None)
            await cb.answer("Lock знято")

        @dp.message(F.text == "🗂 Мої заявки/статус")
        async def my_status(message: Message):
            rows = self.db.user_news(message.from_user.id)
            if not rows:
                await message.answer("У вас поки немає заявок.")
                return
            for row in rows:
                await message.answer(f"#{row['id']} — {row['status']}\n{(row['text'] or '')[:250]}", reply_markup=my_news_keyboard(row['id'], row['status']=='PENDING'))

        return dp

    async def _persist_and_show_preview(self, message: Message, state: FSMContext):
        data = await state.get_data()
        self.db.save_draft({
            "draft_id": data["draft_id"], "author_user_id": message.from_user.id, "author_username": message.from_user.username,
            "text": data.get("text", ""), "link": data.get("link"), "location": data.get("location"),
            "media_json": json.dumps(data.get("media", []), ensure_ascii=False), "created_at": now_iso(), "updated_at": now_iso()
        })
        await message.answer(self._build_preview(data), reply_markup=news_preview_keyboard(data["draft_id"]))

    def _build_preview(self, data: dict[str, Any]) -> str:
        return (
            "Прев’ю новини:\n"
            f"Текст: {data.get('text')}\n"
            f"Лінк: {data.get('link') or '-'}\n"
            f"Локація: {data.get('location') or '-'}\n"
            f"Медіа: {len(data.get('media', []))}"
        )

    def _with_location(self, text: str, location: str | None) -> str:
        return f"{text}\n\n📍 {location}" if location else text

    def _is_admin(self, user_id: int) -> bool:
        return any(r["user_id"] == user_id for r in self.db.list_active_admins())

    def _role_of(self, user_id: int) -> str | None:
        for row in self.db.list_active_admins():
            if row["user_id"] == user_id:
                return row["role"]
        return None

    def _can_moderate(self, user_id: int, news: Any) -> bool:
        return news["locked_by_admin_id"] == user_id or self._role_of(user_id) == "owner"

    def _render_admin_card(self, news: Any) -> str:
        created = datetime.fromisoformat(news["created_at"]).astimezone(UTC).strftime("%Y-%m-%d %H:%M")
        return f"🆔 {news['id']}\n🧾 {news['source_title']}\n⏰ {created}\nСтатус: {news['status']}\n\n{news['text']}"

    async def broadcast_to_admins(self, bot: Bot, news_id: int) -> int:
        news = self.db.get_news(news_id)
        if not news:
            return 0
        admins = self.db.list_active_admins()
        if not admins:
            await self.notify_owner_no_admins(bot)
            return 0
        sent = 0
        for admin in admins:
            try:
                await bot.send_message(admin["user_id"], self._render_admin_card(news), reply_markup=moderation_keyboard(news_id, news["source_link"]))
                sent += 1
            except Exception:
                await self._notify_owner_admin_unreachable(bot, str(admin["user_id"]))
        return sent

    async def notify_owner_missing_target(self, bot: Bot):
        await bot.send_message(self.settings.owner_id, "Немає GROUP_ID/THREAD_ID — публікація заблокована")

    async def notify_owner_no_admins(self, bot: Bot):
        await bot.send_message(self.settings.owner_id, "Немає активних адмінів для модерації")

    async def _notify_owner_admin_unreachable(self, bot: Bot, admin_id: str):
        await bot.send_message(self.settings.owner_id, f"⚠️ Не можу написати адміну {admin_id} — закриті ЛС")
