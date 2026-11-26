import importlib
import os
import pkgutil
import triggers
from aiogram import Bot
from aiogram.types import Message


class CommandRouter:
    def __init__(self):
        self.handlers = []
        self._load_triggers()

    def _load_triggers(self):
        """Автоматически загружает все модули из папки triggers."""
        package_path = os.path.dirname(triggers.__file__)
        for _, module_name, _ in pkgutil.iter_modules([package_path]):
            module = importlib.import_module(f"triggers.{module_name}")
            if hasattr(module, "KEYWORDS") and hasattr(module, "execute"):
                for kw in module.KEYWORDS:
                    self.handlers.append({
                        "name": module_name,
                        "keyword": kw.lower(),
                        "execute": module.execute,
                    })
        # Сортируем по убыванию длины триггера, чтобы "список дел" срабатывал раньше "список"
        self.handlers.sort(key=lambda x: len(x["keyword"]), reverse=True)
        print(f"Загружено ключевых слов триггеров: {len(self.handlers)}", flush=True)

    async def dispatch(self, bot: Bot, target_msg: Message, raw_text: str) -> bool:
        """
        Ищет подходящий триггер в начале фразы и вызывает его.
        Возвращает True, если команда найдена и выполнена, иначе False.
        """
        clean_text = raw_text.strip()
        lower_text = clean_text.lower()

        for handler in self.handlers:
            kw = handler["keyword"]
            if lower_text.startswith(kw):
                # Проверяем, что после ключевого слова идёт конец строки или разделитель (не часть другого слова)
                rest = clean_text[len(kw):]
                if rest and rest[0].isalnum():
                    continue

                payload = rest.lstrip(" ,.:-!?")
                await handler["execute"](bot, target_msg, payload)
                return True

        return False
