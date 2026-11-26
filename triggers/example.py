from datetime import datetime
from pathlib import Path
from llm import ask_yandex_gpt

KEYWORDS = ["", ""]

SYSTEM_PROMPT = (
    ""
    ""
)

async def execute(text: str, doc_msg, context: dict):
    if not text:
        await doc_msg.reply("")
        return

    clean_note = await ask_yandex_gpt(
        context["yandex_key"], context["folder_id"], SYSTEM_PROMPT, text
    ) or (text[0].upper() + text[1:] + ".")

    # Сохраняем заметку в локальный файл на Raspberry Pi
    memory_file = Path.home() / "voice2text" / "memory.txt"
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    with open(memory_file, "a", encoding="utf-8") as f:
        f.write(f"[{timestamp}] {clean_note}\n")

    sent = await doc_msg.reply(f"🧠 Запомнил:\n\n{clean_note}"[:4096])
    try:
        await sent.pin(disable_notification=True)
    except Exception:
        pass
