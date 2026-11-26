"""Образец триггера. Файлы с именем на «_» роутер не загружает.

Чтобы добавить команду: скопируйте файл под новым именем (например, my_trigger.py),
задайте KEYWORDS и реализуйте execute. Контракт описан в triggers/__init__.py.
"""

from aiogram import Bot
from aiogram.types import Message

from yandex_api import run_yandex_gpt

# Фраза, с которой начинается распознанный текст. Регистр не важен.
KEYWORDS = ["пример"]

SYSTEM_PROMPT = (
    "Ты технический ассистент. Верни только готовый результат без вступлений и тегов."
)


async def execute(bot: Bot, target_msg: Message, payload: str) -> None:
    if not payload:
        await target_msg.reply("⚠️ Продиктуйте текст после слова «Пример».")
        return

    result = await run_yandex_gpt(SYSTEM_PROMPT, payload) or payload
    await target_msg.reply(f"🧪 {result}")
