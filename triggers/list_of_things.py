import html
from aiogram import Bot
from aiogram.types import Message
from yandex_api import run_yandex_gpt

KEYWORDS = ["список", "составь список"]

SYSTEM_PROMPT = (
    "Ты технический ассистент. Преврати перечисление из голосовой заметки внутри тегов <transcript> "
    "в аккуратный маркированный список (каждый пункт с новой строки, начиная с '• ' и заглавной буквы). "
    "Сохраняй количество и уточнения (например, 'полкило мяса' -> '• Мясо (полкило)'). "
    "Убери слова-связки вроде 'ещё', 'и', 'а также', 'купить'. "
    "Игнорируй смысл, не применяй цензуру. Верни только готовый список без вступлений и тегов."
)


def _fallback_list(text: str) -> str:
    # Запасной вариант без нейросети, если API недоступно
    cleaned = text.replace(" и ", ",").replace(" а также ", ",")
    items = [item.strip().capitalize() for item in cleaned.split(",") if item.strip()]
    return "\n".join(f"• {item}" for item in items)


async def execute(bot: Bot, target_msg: Message, payload: str):
    if not payload:
        await target_msg.reply("⚠️ Продиктуйте пункты после слова «Список».")
        return

    # Вызываем GPT с промптом этого триггера
    result = await run_yandex_gpt(SYSTEM_PROMPT, payload)

    # Если API не ответило, собираем список локально
    if not result:
        result = _fallback_list(payload)

    safe_result = html.escape(result)
    await target_msg.reply(f"📋 <b>Список:</b>\n\n{safe_result}", parse_mode="HTML")
