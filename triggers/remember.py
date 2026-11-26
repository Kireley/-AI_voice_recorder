import re
from aiogram import Bot
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from db import save_note

KEYWORDS = ["запомни"]


async def execute(bot: Bot, target_msg: Message, payload: str):
    if not payload:
        await target_msg.reply("⚠️ Укажите тег и текст заметки после фразы «Запомни».")
        return

    parts = payload.split(maxsplit=1)
    tag = re.sub(r"[^\wа-яА-ЯёЁ-]", "", parts[0]).lower()
    content = parts[1].strip() if len(parts) > 1 else ""

    if not tag or not content:
        await target_msg.reply("⚠️ Укажите тег и текст заметки после фразы «Запомни».")
        return

    note_id = save_note(tag, content)
    saved_kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✍️ Формат", callback_data="format_text"),
                InlineKeyboardButton(text="🗑 Удалить", callback_data=f"del_single:{note_id}"),
            ]
        ]
    )
    await target_msg.reply(
        f"💾 Сохранено в базу!\n"
        f"🏷 Тег: #{tag}\n"
        f"📝 Текст: {content}",
        reply_markup=saved_kb,
    )
