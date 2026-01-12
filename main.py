#!/usr/bin/env python3
"""
Telegram бот для учёта 3D-печати деталей.
Автор: codedetective221b ну  и конечно клод. Хотя скорее клод ну и я сбоки встал
"""

import json
import logging
from pathlib import Path
from dataclasses import dataclass, asdict, field
from typing import Optional, Dict, Any
from enum import Enum, auto

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.ext import (
    ApplicationBuilder,
    ContextTypes,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
)
from telegram.error import TelegramError

# ═══════════════════════════════════════════════════════════
#                         НАСТРОЙКИ
# ═══════════════════════════════════════════════════════════

TOKEN = "8192063748:AAGFyNTjLhLUWp0edBojW8WPq4Zv-z_RxjU"  # Замени на свой!
DATA_FILE = Path("parts.json")
ADMIN_IDS: list[int] = []  # ID пользователей с доступом (пусто = все)

# Логирование
logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(message)s",
    level=logging.INFO
)
log = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════
#                     СОСТОЯНИЯ ПОЛЬЗОВАТЕЛЯ
# ═══════════════════════════════════════════════════════════

class Step(Enum):
    IDLE = auto()
    NAME = auto()          # Ввод названия
    COUNT = auto()         # Ввод количества
    STL = auto()           # Загрузка STL
    PHOTO = auto()         # Загрузка фото при создании
    PHOTO_UPDATE = auto()  # Обновление фото существующей детали
    STL_UPDATE = auto()    # Обновление STL существующей детали


@dataclass
class UserState:
    step: Step = Step.IDLE
    part_name: str = ""


STATES: Dict[int, UserState] = {}


def get_state(uid: int) -> UserState:
    if uid not in STATES:
        STATES[uid] = UserState()
    return STATES[uid]


def reset_state(uid: int):
    STATES[uid] = UserState()


# ═══════════════════════════════════════════════════════════
#                         ХРАНИЛИЩЕ
# ═══════════════════════════════════════════════════════════

@dataclass
class Part:
    need: int
    printed: int = 0
    stl: Optional[str] = None
    photo: Optional[str] = None

    @property
    def done(self) -> bool:
        return self.need > 0 and self.printed >= self.need

    @property
    def left(self) -> int:
        return max(0, self.need - self.printed)

    @property
    def percent(self) -> int:
        return int(self.printed / self.need * 100) if self.need else 0


def load_db() -> Dict[str, Dict]:
    try:
        if DATA_FILE.exists():
            return json.loads(DATA_FILE.read_text("utf-8"))
    except Exception as e:
        log.error(f"Ошибка загрузки: {e}")
    return {}


def save_db(data: Dict[str, Dict]):
    DATA_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False), "utf-8")


def get_part(name: str) -> Optional[Part]:
    db = load_db()
    return Part(**db[name]) if name in db else None


def set_part(name: str, part: Part):
    db = load_db()
    db[name] = asdict(part)
    save_db(db)


def del_part(name: str) -> bool:
    db = load_db()
    if name in db:
        del db[name]
        save_db(db)
        return True
    return False


# ═══════════════════════════════════════════════════════════
#                         КЛАВИАТУРЫ
# ═══════════════════════════════════════════════════════════

def kb_main():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Добавить деталь", callback_data="add")],
        [InlineKeyboardButton("📋 Все детали", callback_data="list")],
    ])


def kb_list(db: Dict[str, Dict]):
    rows = []
    for name in sorted(db.keys()):
        p = Part(**db[name])
        icon = "✅" if p.done else "🔄"
        rows.append([InlineKeyboardButton(
            f"{icon} {name}  [{p.printed}/{p.need}]",
            callback_data=f"v:{name}"
        )])
    rows.append([InlineKeyboardButton("🏠 Меню", callback_data="home")])
    return InlineKeyboardMarkup(rows)


def kb_part(name: str, p: Part):
    rows = [
        # Счётчик
        [
            InlineKeyboardButton("➖", callback_data=f"dec:{name}"),
            InlineKeyboardButton(f"🖨 {p.printed}", callback_data="noop"),
            InlineKeyboardButton("➕", callback_data=f"inc:{name}"),
        ],
    ]

    # STL
    if p.stl:
        rows.append([
            InlineKeyboardButton("📥 Скачать STL", callback_data=f"get_stl:{name}"),
            InlineKeyboardButton("🗑", callback_data=f"del_stl:{name}"),
        ])
    else:
        rows.append([
            InlineKeyboardButton("📎 Загрузить STL", callback_data=f"add_stl:{name}")
        ])

    # Фото
    if p.photo:
        rows.append([
            InlineKeyboardButton("🖼 Показать фото", callback_data=f"get_photo:{name}"),
            InlineKeyboardButton("🗑", callback_data=f"del_photo:{name}"),
        ])
    else:
        rows.append([
            InlineKeyboardButton("📷 Загрузить фото", callback_data=f"add_photo:{name}")
        ])

    rows.append([InlineKeyboardButton("🗑 Удалить деталь", callback_data=f"delete:{name}")])
    rows.append([InlineKeyboardButton("⬅️ Назад", callback_data="list")])
    return InlineKeyboardMarkup(rows)


def kb_cancel():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("❌ Отмена", callback_data="cancel")]
    ])


def kb_skip(what: str):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"⏭ Пропустить", callback_data=f"skip_{what}")],
        [InlineKeyboardButton("❌ Отмена", callback_data="cancel")],
    ])


# ═══════════════════════════════════════════════════════════
#                      ФОРМАТИРОВАНИЕ
# ═══════════════════════════════════════════════════════════

def fmt_part(name: str, p: Part) -> str:
    status = "✅ ГОТОВО" if p.done else "🔄 В процессе"
    bar_len = 10
    filled = int(p.percent / 100 * bar_len)
    bar = "█" * filled + "░" * (bar_len - filled)

    return (
        f"{status}\n\n"
        f"🔧 *{name}*\n\n"
        f"`[{bar}]` {p.percent}%\n\n"
        f"📦 Нужно: {p.need}\n"
        f"🖨 Напечатано: {p.printed}\n"
        f"📍 Осталось: {p.left}\n\n"
        f"📎 STL: {'✓' if p.stl else '✗'}  |  🖼 Фото: {'✓' if p.photo else '✗'}"
    )


def fmt_stats(db: Dict[str, Dict]) -> str:
    if not db:
        return "📋 *Список пуст*\n\nДобавьте первую деталь!"

    total = len(db)
    done = sum(1 for d in db.values() if Part(**d).done)
    need = sum(Part(**d).need for d in db.values())
    printed = sum(Part(**d).printed for d in db.values())
    pct = int(printed / need * 100) if need else 0

    return (
        f"📊 *Статистика*\n\n"
        f"Деталей: {total}  (✅ {done} / 🔄 {total - done})\n"
        f"Всего: {printed} / {need}  ({pct}%)"
    )


# ═══════════════════════════════════════════════════════════
#                        ОБРАБОТЧИКИ
# ═══════════════════════════════════════════════════════════

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    reset_state(update.effective_user.id)
    await update.message.reply_text(
        "🖨 *Учёт 3D-печати*\n\n"
        "Управляй деталями, STL и фото.",
        parse_mode="Markdown",
        reply_markup=kb_main()
    )


async def on_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    uid = update.effective_user.id
    data = q.data

    try:
        # ─────────── НАВИГАЦИЯ ───────────
        if data == "home":
            reset_state(uid)
            await safe_edit(q.message, "🖨 *Учёт 3D-печати*", kb_main())

        elif data == "list":
            reset_state(uid)
            db = load_db()
            await safe_edit(q.message, fmt_stats(db), kb_list(db))

        elif data == "cancel":
            reset_state(uid)
            await safe_edit(q.message, "❌ Отменено", kb_main())

        elif data == "noop":
            pass  # Ничего не делаем

        # ─────────── СОЗДАНИЕ ───────────
        elif data == "add":
            get_state(uid).step = Step.NAME
            await safe_edit(q.message, "✏️ Введите название детали:", kb_cancel())

        elif data == "skip_stl":
            st = get_state(uid)
            st.step = Step.PHOTO
            await safe_edit(
                q.message,
                f"📷 Отправьте фото *{st.part_name}*\n(или пропустите)",
                kb_skip("photo")
            )

        elif data == "skip_photo":
            st = get_state(uid)
            reset_state(uid)
            await safe_edit(
                q.message,
                f"✅ Деталь *{st.part_name}* создана!",
                kb_main()
            )

        # ─────────── ПРОСМОТР ───────────
        elif data.startswith("v:"):
            name = data[2:]
            await show_part(q.message, ctx, name)

        # ─────────── СЧЁТЧИК ───────────
        elif data.startswith("inc:"):
            name = data[4:]
            p = get_part(name)
            if p and p.printed < p.need:
                p.printed += 1
                set_part(name, p)
            await show_part(q.message, ctx, name)

        elif data.startswith("dec:"):
            name = data[4:]
            p = get_part(name)
            if p and p.printed > 0:
                p.printed -= 1
                set_part(name, p)
            await show_part(q.message, ctx, name)

        # ─────────── STL ───────────
        elif data.startswith("add_stl:"):
            name = data[8:]
            st = get_state(uid)
            st.step = Step.STL_UPDATE
            st.part_name = name
            await safe_delete_and_send(q.message, ctx,
                f"📎 Отправьте STL для *{name}*", kb_cancel())

        elif data.startswith("get_stl:"):
            name = data[8:]
            p = get_part(name)
            if p and p.stl:
                await ctx.bot.send_document(q.message.chat_id, p.stl, caption=f"📎 {name}.stl")

        elif data.startswith("del_stl:"):
            name = data[8:]
            p = get_part(name)
            if p:
                p.stl = None
                set_part(name, p)
            await show_part(q.message, ctx, name)

        # ─────────── ФОТО ───────────
        elif data.startswith("add_photo:"):
            name = data[10:]
            st = get_state(uid)
            st.step = Step.PHOTO_UPDATE
            st.part_name = name
            await safe_delete_and_send(q.message, ctx,
                f"📷 Отправьте фото *{name}*", kb_cancel())

        elif data.startswith("get_photo:"):
            name = data[10:]
            p = get_part(name)
            if p and p.photo:
                await ctx.bot.send_photo(q.message.chat_id, p.photo, caption=f"🖼 {name}")

        elif data.startswith("del_photo:"):
            name = data[10:]
            p = get_part(name)
            if p:
                p.photo = None
                set_part(name, p)
            await show_part(q.message, ctx, name)

        # ─────────── УДАЛЕНИЕ ───────────
        elif data.startswith("delete:"):
            name = data[7:]
            del_part(name)
            await safe_delete_and_send(q.message, ctx,
                f"🗑 *{name}* удалена", kb_main())

    except TelegramError as e:
        log.error(f"Callback error: {e}")


async def on_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    st = get_state(uid)
    text = update.message.text.strip()

    if st.step == Step.NAME:
        db = load_db()
        if text in db:
            await update.message.reply_text(
                f"❌ *{text}* уже есть!\nВведите другое:",
                parse_mode="Markdown", reply_markup=kb_cancel()
            )
            return
        st.part_name = text
        st.step = Step.COUNT
        await update.message.reply_text(
            f"📦 Сколько *{text}* нужно напечатать?",
            parse_mode="Markdown", reply_markup=kb_cancel()
        )

    elif st.step == Step.COUNT:
        try:
            cnt = int(text)
            if cnt <= 0:
                raise ValueError
            set_part(st.part_name, Part(need=cnt))
            st.step = Step.STL
            await update.message.reply_text(
                f"📎 Отправьте STL для *{st.part_name}*\n(или пропустите)",
                parse_mode="Markdown", reply_markup=kb_skip("stl")
            )
        except ValueError:
            await update.message.reply_text("❌ Введите число > 0")


async def on_document(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    st = get_state(uid)
    file_id = update.message.document.file_id

    if st.step == Step.STL and st.part_name:
        p = get_part(st.part_name)
        if p:
            p.stl = file_id
            set_part(st.part_name, p)
            st.step = Step.PHOTO
            await update.message.reply_text(
                f"✅ STL добавлен!\n\n📷 Отправьте фото *{st.part_name}*\n(или пропустите)",
                parse_mode="Markdown", reply_markup=kb_skip("photo")
            )

    elif st.step == Step.STL_UPDATE and st.part_name:
        p = get_part(st.part_name)
        if p:
            p.stl = file_id
            set_part(st.part_name, p)
            reset_state(uid)
            await update.message.reply_text(
                f"✅ STL обновлён!",
                reply_markup=kb_main()
            )


async def on_photo(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    st = get_state(uid)
    photo_id = update.message.photo[-1].file_id  # Лучшее качество

    if st.step == Step.PHOTO and st.part_name:
        p = get_part(st.part_name)
        if p:
            p.photo = photo_id
            set_part(st.part_name, p)
            reset_state(uid)
            await update.message.reply_text(
                f"✅ Деталь *{st.part_name}* создана!",
                parse_mode="Markdown", reply_markup=kb_main()
            )

    elif st.step == Step.PHOTO_UPDATE and st.part_name:
        p = get_part(st.part_name)
        if p:
            p.photo = photo_id
            set_part(st.part_name, p)
            reset_state(uid)
            await update.message.reply_photo(
                photo_id,
                caption=fmt_part(st.part_name, p),
                parse_mode="Markdown",
                reply_markup=kb_part(st.part_name, p)
            )


# ═══════════════════════════════════════════════════════════
#                         ХЕЛПЕРЫ
# ═══════════════════════════════════════════════════════════

async def safe_edit(msg, text: str, markup):
    """Безопасное редактирование (текст или caption)"""
    try:
        if msg.photo:
            await msg.edit_caption(text, parse_mode="Markdown", reply_markup=markup)
        else:
            await msg.edit_text(text, parse_mode="Markdown", reply_markup=markup)
    except TelegramError:
        pass


async def safe_delete_and_send(msg, ctx, text: str, markup):
    """Удалить сообщение и отправить новое"""
    try:
        await msg.delete()
    except TelegramError:
        pass
    await ctx.bot.send_message(
        msg.chat_id, text, parse_mode="Markdown", reply_markup=markup
    )


async def show_part(msg, ctx, name: str):
    """Показать деталь (с фото или без)"""
    p = get_part(name)
    if not p:
        await safe_edit(msg, "❌ Деталь не найдена", kb_main())
        return

    text = fmt_part(name, p)
    markup = kb_part(name, p)

    if p.photo:
        try:
            await msg.delete()
        except TelegramError:
            pass
        await ctx.bot.send_photo(
            msg.chat_id, p.photo,
            caption=text, parse_mode="Markdown", reply_markup=markup
        )
    else:
        await safe_edit(msg, text, markup)


# ═══════════════════════════════════════════════════════════
#                           MAIN
# ═══════════════════════════════════════════════════════════

def main():
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CallbackQueryHandler(on_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    app.add_handler(MessageHandler(filters.Document.ALL, on_document))
    app.add_handler(MessageHandler(filters.PHOTO, on_photo))

    log.info("🚀 Бот запущен!")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
