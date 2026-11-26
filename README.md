# VoiceAgent

Голосовой заметочник: ESP32 пишет WAV по кнопке → сервер распознаёт речь (Yandex
SpeechKit) → отправляет голосовое в Telegram → выполняет голосовую команду
(`запомни`, `список`, …) или просто показывает расшифровку.

## Установка

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Нужен **ffmpeg** в PATH — без него не работает конвертация в OGG/Opus.
Проверка: `ffmpeg -version`. В main.py есть такая же проверка при старте.

## Настройка

```powershell
Copy-Item .env.example .env
```

Заполнить в `.env`:

| Переменная | Назначение |
|---|---|
| `VOICEAGENT_BOT_TOKEN` | токен бота от @BotFather |
| `VOICEAGENT_YANDEX_API_KEY` | API-ключ сервисного аккаунта Yandex Cloud |
| `VOICEAGENT_FOLDER_ID` | folder id в Yandex Cloud |
| `VOICEAGENT_UPLOAD_TOKEN` | общий секрет с ESP32 (`X-Upload-Token`) |
| `VOICEAGENT_CHAT_ID` | id чата, куда бот шлёт голосовые |
| `VOICEAGENT_PROXY_URL` | необязательно: прокси для Telegram |
| `VOICEAGENT_HTTP_HOST` / `_PORT` | необязательно: адрес HTTP-приёмника (по умолчанию `0.0.0.0:8000`) |

`.env` читается при импорте `config.py`; переменные окружения имеют приоритет
над файлом. Пустое значение обязательной переменной — ошибка на старте.

## Запуск

```powershell
.venv\Scripts\python.exe main.py
```

Сервер слушает `POST /upload` (заголовки `X-Upload-Token`, `X-Filename`,
тело — WAV), принимает файл, ставит обработку в очередь (максимум 2
одновременно) и возвращает 200 сразу после сохранения.

## Команды в Telegram

- `/taglist` — все теги с количеством заметок
- `/tag <тег>` — заметки по тегу (по 10 на страницу, кнопки «Продолжить» и «Удалить»)
- кнопка «✍️ Формат» — расставить пунктуацию через YandexGPT
- голосом: «запомни <тег> <текст>», «список <перечисление>»

## Как добавить голосовую команду

1. Скопировать `triggers/_template.py` в `triggers/my_command.py`.
2. Задать `KEYWORDS` (непустые строки, регистр не важен).
3. Реализовать `async def execute(bot, target_msg, payload) -> None`.

Модуль подхватится при следующем старте: роутер импортирует все файлы из
`triggers/`, кроме начинающихся с `_`. Полный контракт — в
`triggers/__init__.py`. Ключевые слова сортируются по длине, срабатывает
первое совпадение; ошибка внутри триггера логируется и не роняет обработку.

## Устройство проекта

```
main.py            HTTP-приёмник, запуск бота, пайплайн WAV → OGG → Telegram
bot_handlers.py    Telegram-обвязка: /tag, /taglist, кнопки, приём WAV
command_router.py  загрузка и вызов триггеров
triggers/          голосовые команды (по модулю на команду)
yandex_api.py      SpeechKit (STT) и YandexGPT
db.py              SQLite: заметки с тегами
wav_to_ogg.py      конвертация через ffmpeg
config.py          env-конфигурация
esp32_dep/         прошивка MicroPython для ESP32
```

Логи пишутся в `data/voiceagent.log` (ротация: 1 МБ × 3 файла) и в консоль.
Файлы из `data/inbox/` старше 7 дней удаляются при старте.

## ESP32

Скопировать `esp32_dep/config.py.example` в `esp32_dep/config.py` на устройстве,
указать Wi-Fi, IP сервера и тот же `UPLOAD_TOKEN`. Запись — удержание кнопки
на GPIO 4, файл пишется на SD и отправляется на `/upload`.

## Ограничения

- HTTP без TLS: `X-Upload-Token` передаётся открытым текстом. Годится для
  домашней сети, но не для интернета.
- Хендлеры бота не проверяют, кто пишет: доступ к заметкам имеет любой, кто
  знает имя бота. Для личного использования это осознанный компромисс.
- Синхронные вызовы SQLite выполняются в event loop. Запросы мелкие и
  индексированы, но при росте базы их стоит вынести в `asyncio.to_thread`.
