from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup


def user_main_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📰 Надіслати новину")],
            [KeyboardButton(text="📌 Правила подачі"), KeyboardButton(text="☎️ Зв’язок з адмінами")],
            [KeyboardButton(text="🗂 Мої заявки/статус")],
        ],
        resize_keyboard=True,
    )


def news_preview_keyboard(draft_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✅ Надіслати на модерацію", callback_data=f"draft:submit:{draft_id}")],
            [InlineKeyboardButton(text="✏️ Редагувати", callback_data=f"draft:edit:{draft_id}")],
            [InlineKeyboardButton(text="❌ Скасувати", callback_data=f"draft:cancel:{draft_id}")],
        ]
    )


def moderation_keyboard(news_id: int, original_url: str | None = None) -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(text="🔒 Прийняти", callback_data=f"claim:{news_id}")],
        [InlineKeyboardButton(text="✏️ Редагувати", callback_data=f"edit_locked:{news_id}")],
        [InlineKeyboardButton(text="✅ Опублікувати", callback_data=f"publish:{news_id}")],
        [InlineKeyboardButton(text="❌ Відхилити", callback_data=f"reject:{news_id}")],
        [InlineKeyboardButton(text="🔓 Зняти lock", callback_data=f"unlock:{news_id}")],
        [InlineKeyboardButton(text="🔄 Оновити", callback_data=f"refresh:{news_id}")],
    ]
    if original_url:
        buttons.insert(1, [InlineKeyboardButton(text="🔗 Оригінал", url=original_url)])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def my_news_keyboard(news_id: int, can_cancel: bool) -> InlineKeyboardMarkup | None:
    if not can_cancel:
        return None
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="❌ Скасувати", callback_data=f"cancel_pending:{news_id}")]]
    )


def admin_panel_button() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="🛠 Адмін-панель")]],
        resize_keyboard=True,
    )


def admin_panel_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👤 Акаунти (Telethon)", callback_data="panel:accounts")],
        [InlineKeyboardButton(text="📡 Джерела (канали/групи)", callback_data="panel:sources")],
        [InlineKeyboardButton(text="🧾 Черга модерації", callback_data="panel:queue")],
        [InlineKeyboardButton(text="⚙️ Налаштування автопосту", callback_data="panel:autopost")],
        [InlineKeyboardButton(text="📊 Статистика / Логи", callback_data="panel:stats")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="panel:back")],
    ])


def accounts_keyboard(rows) -> InlineKeyboardMarkup:
    kb = [[InlineKeyboardButton(text="➕ Додати акаунт", callback_data="panel:accounts:add")]]
    for r in rows:
        icon = "🟢" if r["status"] == "READY" else ("🟡" if r["status"].startswith("WAIT") else ("⚫" if not r["is_enabled"] else "🔴"))
        kb.append([InlineKeyboardButton(text=f"{icon} #{r['id']} {r['title']}", callback_data=f"panel:accounts:view:{r['id']}")])
    kb.append([InlineKeyboardButton(text="🔙 Назад", callback_data="panel:root")])
    return InlineKeyboardMarkup(inline_keyboard=kb)


def account_actions_keyboard(account_id: int, enabled: bool) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=("🚫 Вимкнути" if enabled else "✅ Увімкнути"), callback_data=f"acc:toggle:{account_id}")],
        [InlineKeyboardButton(text="🔄 Перевірити сесію", callback_data=f"acc:check:{account_id}")],
        [InlineKeyboardButton(text="🗑 Видалити", callback_data=f"acc:delete:{account_id}")],
        [InlineKeyboardButton(text="🔙 До акаунтів", callback_data="panel:accounts")],
    ])


def sources_keyboard(rows) -> InlineKeyboardMarkup:
    kb = [[InlineKeyboardButton(text="➕ Додати джерело", callback_data="src:add")]]
    for r in rows:
        icon = "✅" if r["is_enabled"] else "🚫"
        kb.append([InlineKeyboardButton(text=f"{icon} #{r['id']} {r['title']}", callback_data=f"src:detail:{r['id']}")])
    kb.append([InlineKeyboardButton(text="🔙 Назад", callback_data="panel:root")])
    return InlineKeyboardMarkup(inline_keyboard=kb)


def source_actions_keyboard(source_id: int, enabled: bool, allow_autopost: bool, mode: str) -> InlineKeyboardMarkup:
    mode_next = "KEYWORDS" if mode == "OFF" else "OFF"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=("🚫 Вимкнути" if enabled else "✅ Увімкнути"), callback_data=f"src:toggle:{source_id}")],
        [InlineKeyboardButton(text=("⚡ Автопост ON" if allow_autopost else "⚪ Автопост OFF"), callback_data=f"src:autopost:{source_id}")],
        [InlineKeyboardButton(text=f"Режим: {mode} → {mode_next}", callback_data=f"src:mode:{source_id}:{mode_next}")],
        [InlineKeyboardButton(text="🗑 Видалити", callback_data=f"src:delete:{source_id}")],
        [InlineKeyboardButton(text="🔙 До джерел", callback_data="panel:sources")],
    ])
