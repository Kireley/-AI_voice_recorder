import importlib
import logging
import os
import pkgutil
from typing import Awaitable, Callable

import triggers
from aiogram import Bot
from aiogram.types import Message

logger = logging.getLogger(__name__)

TriggerFunc = Callable[[Bot, Message, str], Awaitable[None]]


class CommandRouter:
    """Диспетчер голосовых триггеров из пакета `triggers`.

    Контракт модуля-триггера описан в `triggers/__init__.py`.
    Ошибка внутри одного триггера не ломает обработку остальных.
    """

    def __init__(self):
        self.handlers: list[dict] = []
        self._load_triggers()

    def _load_triggers(self) -> None:
        """Загрузить все модули из папки triggers, кроме служебных (_template и т.п.)."""
        package_path = os.path.dirname(triggers.__file__)

        for _, module_name, _ in pkgutil.iter_modules([package_path]):
            if module_name.startswith("_"):
                continue

            try:
                module = importlib.import_module(f"triggers.{module_name}")
            except Exception:
                logger.exception("Не удалось загрузить триггер %s", module_name)
                continue

            keywords = getattr(module, "KEYWORDS", None)
            execute: TriggerFunc | None = getattr(module, "execute", None)
            if not keywords or not callable(execute):
                logger.warning(
                    "Триггер %s пропущен: нужны KEYWORDS и async def execute", module_name
                )
                continue

            for kw in keywords:
                if not kw or not kw.strip():
                    # Пустое слово совпало бы с любым текстом и перехватило всё.
                    logger.warning("Триггер %s: пустое ключевое слово пропущено", module_name)
                    continue
                self.handlers.append(
                    {
                        "name": module_name,
                        "keyword": kw.strip().lower(),
                        "execute": execute,
                    }
                )

        # Сортируем по убыванию длины, чтобы "список дел" срабатывал раньше "список"
        self.handlers.sort(key=lambda x: len(x["keyword"]), reverse=True)
        names = ", ".join(sorted({h["name"] for h in self.handlers})) or "нет"
        logger.info("Загружено триггеров: %d (%s)", len(self.handlers), names)

    async def dispatch(self, bot: Bot, target_msg: Message, raw_text: str) -> bool:
        """Найти триггер в начале фразы и выполнить его.

        Возвращает True, если команда найдена (даже если упала), иначе False.
        """
        clean_text = (raw_text or "").strip()
        if not clean_text:
            return False

        lower_text = clean_text.lower()

        for handler in self.handlers:
            kw = handler["keyword"]
            if not lower_text.startswith(kw):
                continue

            # После ключевого слова должен идти конец строки или разделитель,
            # иначе "список" сработает внутри слова "списочек".
            rest = clean_text[len(kw) :]
            if rest and rest[0].isalnum():
                continue

            payload = rest.lstrip(" ,.:-!?")
            try:
                await handler["execute"](bot, target_msg, payload)
            except Exception:
                logger.exception(
                    "Триггер %s упал на тексте %r", handler["name"], clean_text[:100]
                )
                await target_msg.reply(
                    f"⚠️ Команда «{handler['keyword']}» не сработала, подробности в логе."
                )
            return True

        return False
