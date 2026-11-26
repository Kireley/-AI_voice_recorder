import html
import io
import re
from aiogram import Bot, Router, F
from aiogram.filters import Command
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from config import CHAT_ID
from db import save_note, get_all_tags, get_notes_by_tag, delete_note
from yandex_api import transcribe_yandex, format_punctuation
from command_router import CommandRouter

command_router = CommandRouter()

router = Router()

SEPARATOR = "\n__________________\n"

format_kb = InlineKeyboardMarkup(
    inline_keyboard=[
        [InlineKeyboardButton(text="✍️ Формат", callback_data="format_text")]
    ]
)





# Обновлённая функция process_recognized_text:
async def process_recognized_text(bot: Bot, target_msg: Message, raw_text: str):
    if not raw_text:
        await target_msg.reply("🔇 Речь не распознана.")
        return

    # Пытаемся выполнить голосовой триггер из папки triggers
    is_handled = await command_router.dispatch(bot, target_msg, raw_text)
    if is_handled:
        return

    # Действие по умолчанию (обычная расшифровка)
    header = "📝 "
    max_len = 4096 - len(header)
    if len(raw_text) <= max_len:
        await target_msg.reply(f"{header}{raw_text}", reply_markup=format_kb)
    else:
        await target_msg.reply(f"{header}{raw_text[:max_len]}", reply_markup=format_kb)
        for i in range(max_len, len(raw_text), 4096):
            await bot.send_message(CHAT_ID, raw_text[i : i + 4096], reply_markup=format_kb)


def build_notes_page(tag: str, offset: int = 0) -> tuple[str, InlineKeyboardMarkup | None]:
    notes, has_more = get_notes_by_tag(tag, offset=offset, limit=10)
    if not notes:
        return f"🔍 Заметок с тегом <b>#{html.escape(tag)}</b> не найдено.", None

    blocks = []
    for idx, (note_id, content, created_at) in enumerate(notes, start=offset + 1):
        safe_content = html.escape(content)
        blocks.append(f"<b>{idx}.</b> <i>[{created_at}]</i>\n{safe_content}")

    header = f"🏷 Заметки по тегу <b>#{html.escape(tag)}</b> (показаны {offset + 1}–{offset + len(notes)}):\n\n"
    body = SEPARATOR.join(blocks)
    full_text = header + body

    if len(full_text) > 4096:
        full_text = full_text[:4090] + "\n..."

    buttons = []
    if has_more:
        next_offset = offset + 10
        buttons.append([InlineKeyboardButton(text="Продолжить ➡️", callback_data=f"tag_more:{tag}:{next_offset}")])

    # Добавляем кнопку перехода в режим удаления
    buttons.append([InlineKeyboardButton(text="🗑 Удалить запись", callback_data=f"del_menu:{tag}:{offset}")])

    kb = InlineKeyboardMarkup(inline_keyboard=buttons)
    return full_text, kb


async def process_recognized_text(bot: Bot, target_msg: Message, raw_text: str):
    if not raw_text:
        await target_msg.reply("🔇 Речь не распознана.")
        return

    tag, content = parse_remember_command(raw_text)

    if tag is not None:
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
        return

    header = "📝 "
    max_len = 4096 - len(header)
    if len(raw_text) <= max_len:
        await target_msg.reply(f"{header}{raw_text}", reply_markup=format_kb)
    else:
        await target_msg.reply(f"{header}{raw_text[:max_len]}", reply_markup=format_kb)
        for i in range(max_len, len(raw_text), 4096):
            await bot.send_message(CHAT_ID, raw_text[i : i + 4096], reply_markup=format_kb)

@router.callback_query(F.data.startswith("del_single:"))
async def handle_delete_single(callback: CallbackQuery):
    note_id = int(callback.data.split(":")[1])
    if delete_note(note_id):
        await callback.message.edit_text("🗑 Запись удалена из базы.")
        await callback.answer("Удалено")
    else:
        await callback.answer("Запись уже удалена.", show_alert=True)



@router.message(Command("taglist"))
async def cmd_taglist(message: Message):
    tags = get_all_tags()
    if not tags:
        await message.reply("📭 База заметок пока пуста.")
        return

    lines = ["📋 <b>Сохранённые теги:</b>\n"]
    for tag, count in tags:
        safe_tag = html.escape(tag)
        lines.append(f"• #{safe_tag} — {count} шт. (<code>/tag {safe_tag}</code>)")

    text = "\n".join(lines)
    await message.reply(text[:4096], parse_mode="HTML")


@router.message(Command("tag"))
async def cmd_tag(message: Message):
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2 or not parts[1].strip():
        await message.reply("⚠️ Укажите тег после команды. Пример: <code>/tag идеи</code>", parse_mode="HTML")
        return

    raw_tag = parts[1].strip().lstrip("#")
    tag = re.sub(r"[^\wа-яА-ЯёЁ-]", "", raw_tag).lower()

    if not tag:
        await message.reply("⚠️ Некорректный тег.")
        return

    text, kb = build_notes_page(tag, offset=0)
    await message.reply(text, reply_markup=kb, parse_mode="HTML")


@router.callback_query(F.data.startswith("tag_more:"))
async def handle_tag_more(callback: CallbackQuery):
    await callback.answer()
    try:
        _, tag, offset_str = callback.data.split(":", maxsplit=2)
        offset = int(offset_str)
    except ValueError:
        return

    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass

    text, kb = build_notes_page(tag, offset=offset)
    await callback.message.answer(text, reply_markup=kb, parse_mode="HTML")


@router.callback_query(F.data == "format_text")
async def handle_format_callback(callback: CallbackQuery):
    await callback.answer("Форматирую текст...")
    msg = callback.message
    if not msg or not msg.text:
        return

    raw_text = msg.text.removeprefix("📝 ").strip()
    try:
        await msg.edit_reply_markup(reply_markup=None)
    except Exception:
        pass

    formatted_text = await format_punctuation(raw_text)
    new_text = f"✨ {formatted_text}"[:4096]
    if new_text != msg.text:
        await msg.edit_text(new_text)


@router.message(F.document | F.audio)
async def handle_manual_wav(message: Message, bot: Bot):
    media = message.document or message.audio
    filename = getattr(media, "file_name", "") or ""
    if not filename.lower().endswith(".wav"):
        return

    buf = io.BytesIO()
    await bot.download(media, destination=buf)
    raw_text = await transcribe_yandex(buf.getvalue())
    await process_recognized_text(bot, message, raw_text)


@router.callback_query(F.data.startswith("delete_note:"))
async def handle_delete_note(callback: CallbackQuery):
    # Извлекаем id из строки вида "delete_note:15"
    note_id = int(callback.data.split(":")[1])

    is_deleted = delete_note(note_id)

    if is_deleted:
        await callback.message.edit_text("🗑 Запись удалена.")
        await callback.answer("Удалено")
    else:
        await callback.answer("Запись уже была удалена или не найдена.", show_alert=True)


#_________________________

@router.callback_query(F.data.startswith("del_menu:"))
async def handle_delete_menu(callback: CallbackQuery):
    _, tag, offset_str = callback.data.split(":", maxsplit=2)
    offset = int(offset_str)

    notes, _ = get_notes_by_tag(tag, offset=offset, limit=10)
    if not notes:
        await callback.answer("Заметки не найдены.", show_alert=True)
        return

    # Формируем ряды кнопок с номерами заметок (по 5 штук в ряд)
    num_buttons = []
    row = []
    for idx, (note_id, _, _) in enumerate(notes, start=offset + 1):
        row.append(InlineKeyboardButton(text=f"🗑 {idx}", callback_data=f"del_exec:{note_id}:{tag}:{offset}"))
        if len(row) == 5:
            num_buttons.append(row)
            row = []
    if row:
        num_buttons.append(row)

    # Кнопка возврата к обычному виду
    num_buttons.append([InlineKeyboardButton(text="❌ Отмена", callback_data=f"del_cancel:{tag}:{offset}")])

    await callback.message.edit_reply_markup(
        reply_markup=InlineKeyboardMarkup(inline_keyboard=num_buttons)
    )
    await callback.answer("Выберите номер записи для удаления")


@router.callback_query(F.data.startswith("del_exec:"))
async def handle_delete_exec(callback: CallbackQuery):
    _, note_id_str, tag, offset_str = callback.data.split(":", maxsplit=3)
    note_id = int(note_id_str)
    offset = int(offset_str)

    if delete_note(note_id):
        await callback.answer("✅ Запись удалена")
    else:
        await callback.answer("⚠️ Запись уже была удалена", show_alert=True)

    # Обновляем текущую страницу списка
    text, kb = build_notes_page(tag, offset=offset)
    # Если удалили последнюю запись на текущей странице (например, 11-ю), возвращаемся на предыдущую
    if kb is None and offset > 0:
        offset = max(0, offset - 10)
        text, kb = build_notes_page(tag, offset=offset)

    await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")


@router.callback_query(F.data.startswith("del_cancel:"))
async def handle_delete_cancel(callback: CallbackQuery):
    _, tag, offset_str = callback.data.split(":", maxsplit=2)
    offset = int(offset_str)

    _, kb = build_notes_page(tag, offset=offset)
    await callback.message.edit_reply_markup(reply_markup=kb)
    await callback.answer()
