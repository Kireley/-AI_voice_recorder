import html
import io
import logging
import re

from aiogram import Bot, Router, F
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from config import CHAT_ID
from db import get_all_tags, get_notes_by_tag, delete_note
from yandex_api import transcribe_yandex, format_punctuation
from command_router import CommandRouter

logger = logging.getLogger(__name__)

command_router = CommandRouter()

router = Router()

MESSAGE_LIMIT = 4096
SEPARATOR = "\n__________________\n"

format_kb = InlineKeyboardMarkup(
    inline_keyboard=[
        [InlineKeyboardButton(text="✍️ Формат", callback_data="format_text")]
    ]
)





def truncate_html(text: str, limit: int = MESSAGE_LIMIT) -> str:
    """Обрезать текст по границе строки, не разрывая HTML-тег или сущность вида &amp;."""
    if len(text) <= limit:
        return text

    cut = text[: limit - 10]
    newline = cut.rfind("\n")
    if newline > 0:
        cut = cut[:newline]

    amp = cut.rfind("&")
    if amp != -1 and ";" not in cut[amp:]:
        cut = cut[:amp]

    return cut.rstrip() + "\n…"


async def process_recognized_text(bot: Bot, target_msg: Message, raw_text: str):
    """Точка входа для распознанного текста: сначала голосовые триггеры, потом расшифровка."""
    if not raw_text:
        await target_msg.reply("🔇 Речь не распознана.")
        return

    if await command_router.dispatch(bot, target_msg, raw_text):
        return

    header = "📝 "
    max_len = MESSAGE_LIMIT - len(header)
    if len(raw_text) <= max_len:
        await target_msg.reply(f"{header}{raw_text}", reply_markup=format_kb)
        return

    await target_msg.reply(f"{header}{raw_text[:max_len]}", reply_markup=format_kb)
    for i in range(max_len, len(raw_text), MESSAGE_LIMIT):
        await bot.send_message(
            CHAT_ID, raw_text[i : i + MESSAGE_LIMIT], reply_markup=format_kb
        )


def _parse_int(data: str, index: int) -> int | None:
    """Достать целое из callback_data вида 'prefix:123:...'."""
    try:
        return int(data.split(":", maxsplit=3)[index])
    except (IndexError, ValueError):
        return None


async def _safe_edit_text(message: Message | None, text: str, **kwargs) -> None:
    """edit_text, который не падает на MessageNotModified и разметке."""
    if message is None:
        return
    try:
        await message.edit_text(text, **kwargs)
    except TelegramBadRequest as exc:
        logger.warning("Не удалось отредактировать сообщение: %s", exc)


async def _safe_edit_markup(message: Message | None, markup) -> None:
    if message is None:
        return
    try:
        await message.edit_reply_markup(reply_markup=markup)
    except TelegramBadRequest as exc:
        logger.warning("Не удалось изменить клавиатуру: %s", exc)


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

    full_text = truncate_html(full_text)

    buttons = []
    if has_more:
        next_offset = offset + 10
        buttons.append([InlineKeyboardButton(text="Продолжить ➡️", callback_data=f"tag_more:{tag}:{next_offset}")])

    # Добавляем кнопку перехода в режим удаления
    buttons.append([InlineKeyboardButton(text="🗑 Удалить запись", callback_data=f"del_menu:{tag}:{offset}")])

    kb = InlineKeyboardMarkup(inline_keyboard=buttons)
    return full_text, kb


@router.callback_query(F.data.startswith("del_single:"))
async def handle_delete_single(callback: CallbackQuery):
    note_id = _parse_int(callback.data, 1)
    if note_id is None:
        await callback.answer("Некорректные данные кнопки.", show_alert=True)
        return

    if delete_note(note_id):
        await callback.answer("Удалено")
        await _safe_edit_text(callback.message, "🗑 Запись удалена из базы.")
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
    await message.reply(truncate_html(text), parse_mode="HTML")


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

    await _safe_edit_markup(callback.message, None)

    text, kb = build_notes_page(tag, offset=offset)
    await callback.message.answer(text, reply_markup=kb, parse_mode="HTML")


@router.callback_query(F.data == "format_text")
async def handle_format_callback(callback: CallbackQuery):
    msg = callback.message
    raw_text = ""
    if msg is not None and msg.text:
        raw_text = msg.text
        for prefix in ("📝 ", "✨ "):
            raw_text = raw_text.removeprefix(prefix)
        raw_text = raw_text.strip()

    if not raw_text:
        await callback.answer("Нет текста для форматирования.", show_alert=True)
        return

    await callback.answer("Форматирую текст...")
    await _safe_edit_markup(msg, None)

    formatted_text = await format_punctuation(raw_text)
    new_text = f"✨ {formatted_text}"[:MESSAGE_LIMIT]
    if new_text != msg.text:
        await _safe_edit_text(msg, new_text)


@router.message(F.document | F.audio)
async def handle_manual_wav(message: Message, bot: Bot):
    media = message.document or message.audio
    filename = getattr(media, "file_name", "") or ""
    if not filename.lower().endswith(".wav"):
        return

    buf = io.BytesIO()
    try:
        await bot.download(media, destination=buf)
        raw_text = await transcribe_yandex(buf.getvalue())
    except ValueError as exc:
        await message.reply(f"⚠️ {html.escape(str(exc))}")
        return
    except Exception:
        logger.exception("Не удалось обработать загруженный WAV")
        await message.reply("⚠️ Не удалось обработать файл, подробности в логе.")
        return

    await process_recognized_text(bot, message, raw_text)


@router.callback_query(F.data.startswith("del_menu:"))
async def handle_delete_menu(callback: CallbackQuery):
    try:
        _, tag, offset_str = callback.data.split(":", maxsplit=2)
        offset = int(offset_str)
    except ValueError:
        await callback.answer("Некорректные данные кнопки.", show_alert=True)
        return

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

    await _safe_edit_markup(
        callback.message, InlineKeyboardMarkup(inline_keyboard=num_buttons)
    )
    await callback.answer("Выберите номер записи для удаления")


@router.callback_query(F.data.startswith("del_exec:"))
async def handle_delete_exec(callback: CallbackQuery):
    try:
        _, note_id_str, tag, offset_str = callback.data.split(":", maxsplit=3)
        note_id = int(note_id_str)
        offset = int(offset_str)
    except ValueError:
        await callback.answer("Некорректные данные кнопки.", show_alert=True)
        return

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

    await _safe_edit_text(callback.message, text, reply_markup=kb, parse_mode="HTML")


@router.callback_query(F.data.startswith("del_cancel:"))
async def handle_delete_cancel(callback: CallbackQuery):
    try:
        _, tag, offset_str = callback.data.split(":", maxsplit=2)
        offset = int(offset_str)
    except ValueError:
        await callback.answer()
        return

    _, kb = build_notes_page(tag, offset=offset)
    await _safe_edit_markup(callback.message, kb)
    await callback.answer()
