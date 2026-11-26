import asyncio
import hashlib
import logging
import os
import secrets
import shutil
import signal
import time
import uuid
from logging.handlers import RotatingFileHandler
from pathlib import Path

from aiohttp import web
from aiogram import Bot, Dispatcher
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.types import BufferedInputFile

from config import (
    BOT_TOKEN,
    CHAT_ID,
    DATA_DIR,
    HTTP_HOST,
    HTTP_PORT,
    INBOX_DIR,
    MAX_UPLOAD_BYTES,
    PROXY_URL,
    UPLOAD_TOKEN,
)
from db import init_db
from yandex_api import transcribe_yandex
from bot_handlers import router, process_recognized_text
from wav_to_ogg import wav_to_ogg_opus

logger = logging.getLogger(__name__)

session = AiohttpSession(proxy=PROXY_URL, timeout=180) if PROXY_URL else None
bot = Bot(token=BOT_TOKEN, session=session)
dp = Dispatcher()
dp.include_router(router)

# Не больше двух записей одновременно: SpeechKit и Telegram плохо переносят всплески
PIPELINE_LIMIT = asyncio.Semaphore(2)
_background_tasks: set[asyncio.Task] = set()

# Сколько суток хранить необработанные файлы в inbox
INBOX_MAX_AGE_DAYS = 7


def setup_logging(level: int = logging.INFO) -> None:
    handlers: list[logging.Handler] = [logging.StreamHandler()]
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        handlers.append(
            RotatingFileHandler(
                os.path.join(DATA_DIR, "voiceagent.log"),
                maxBytes=1_000_000,
                backupCount=3,
                encoding="utf-8",
            )
        )
    except OSError as exc:
        print(f"Файловый лог недоступен: {exc}", flush=True)

    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
        handlers=handlers,
    )


def _spawn(coro) -> None:
    """Запустить фоновую задачу, удержав ссылку — иначе сборщик мусора её уберёт."""
    task = asyncio.create_task(coro)
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)


async def _send_voice_with_retry(ogg_bytes: bytes, filename: str):
    delays = [0, 5, 15, 30]
    for attempt, delay in enumerate(delays, start=1):
        if delay:
            await asyncio.sleep(delay)
        try:
            return await bot.send_voice(
                chat_id=CHAT_ID,
                voice=BufferedInputFile(ogg_bytes, filename=filename),
                request_timeout=60,
            )
        except Exception as exc:
            logger.warning(
                "Отправка голосового, попытка %s/%s: %r", attempt, len(delays), exc
            )
    return None


async def post_wav_and_transcribe(wav_path: str, filename: str = "record.wav") -> None:
    """Полный цикл: распознать, сконвертировать, отправить голосовое, обработать текст."""
    async with PIPELINE_LIMIT:
        try:
            await _process_wav(wav_path, filename)
        except Exception:
            logger.exception("Ошибка обработки %s", wav_path)


async def _process_wav(wav_path: str, filename: str) -> None:
    wav_bytes = await asyncio.to_thread(Path(wav_path).read_bytes)
    logger.info("Получен файл %s (%s байт)", filename, len(wav_bytes))

    # 1. Распознаём исходный WAV через Яндекс (быстро и без прокси)
    raw_text = await transcribe_yandex(wav_bytes)

    # 2. Конвертируем WAV в лёгкий OGG Opus в памяти
    ogg_bytes = await wav_to_ogg_opus(wav_bytes)
    base_name, _ = os.path.splitext(filename)
    ogg_filename = f"{base_name}.ogg"
    logger.info("Сжато в OGG: %s байт", len(ogg_bytes))

    # 3. Отправляем как голосовое сообщение
    sent_voice_msg = await _send_voice_with_retry(ogg_bytes, ogg_filename)

    # 4. Передаём сообщение с голосовым в обработчик текста
    if sent_voice_msg is None:
        await bot.send_message(
            chat_id=CHAT_ID,
            text=f"⚠️ Голосовое не загрузилось, но текст распознан:\n\n{raw_text}",
        )
        logger.error("Голосовое не доставлено, файл оставлен для разбора: %s", wav_path)
        return

    await process_recognized_text(bot, sent_voice_msg, raw_text)
    await asyncio.to_thread(Path(wav_path).unlink, missing_ok=True)
    logger.info("Обработка завершена")



def cleanup_inbox(max_age_days: int = INBOX_MAX_AGE_DAYS) -> None:
    """Удалить залежавшиеся файлы: неудачные загрузки не должны копиться вечно."""
    inbox = Path(INBOX_DIR)
    if not inbox.is_dir():
        return

    deadline = time.time() - max_age_days * 86400
    removed = 0
    for path in inbox.iterdir():
        try:
            if path.is_file() and path.stat().st_mtime < deadline:
                path.unlink()
                removed += 1
        except OSError:
            logger.warning("Не удалось удалить %s", path)

    if removed:
        logger.info("Удалено старых файлов из inbox: %s", removed)


def _check_ffmpeg() -> None:
    if shutil.which("ffmpeg") is None:
        raise RuntimeError(
            "ffmpeg не найден в PATH. Он нужен для конвертации WAV в OGG/Opus — "
            "установите его и перезапустите."
        )


async def handle_esp32_upload(request: web.Request) -> web.Response:
    if not secrets.compare_digest(request.headers.get("X-Upload-Token", ""), UPLOAD_TOKEN):
        return web.Response(status=401, text="Unauthorized")

    filename = os.path.basename(request.headers.get("X-Filename", "esp32_rec.wav"))
    if not filename.lower().endswith(".wav"):
        return web.Response(status=400, text="WAV file required")

    declared = request.content_length
    if declared is not None and declared > MAX_UPLOAD_BYTES:
        return web.Response(status=413, text="File too large")
    if declared == 0:
        return web.Response(status=400, text="Empty body")

    os.makedirs(INBOX_DIR, exist_ok=True)
    upload_id = uuid.uuid4().hex
    temp_path = Path(INBOX_DIR) / f".{upload_id}.tmp"
    wav_path = Path(INBOX_DIR) / f"{upload_id}.wav"

    try:
        digest = hashlib.sha256()
        total = 0
        with temp_path.open("wb") as output:
            while chunk := await request.content.read(1024 * 1024):
                total += len(chunk)
                if total > MAX_UPLOAD_BYTES:
                    break
                output.write(chunk)
                digest.update(chunk)

        if total > MAX_UPLOAD_BYTES:
            logger.warning("Загрузка %s превысила лимит", filename)
            return web.Response(status=413, text="File too large")
        if total == 0:
            return web.Response(status=400, text="Empty body")
        if declared is not None and total != declared:
            # Обрыв связи: иначе усечённый WAV ушёл бы в распознавание как успешный.
            logger.warning(
                "Обрыв загрузки %s: получено %s из %s байт", filename, total, declared
            )
            return web.Response(status=400, text="Truncated upload")

        temp_path.replace(wav_path)
    except ConnectionResetError as exc:
        logger.warning("ESP32 разорвала соединение во время передачи: %s", exc)
        return web.Response(status=499, text="Client closed request")
    finally:
        temp_path.unlink(missing_ok=True)

    logger.info(
        "Файл сохранён: %s (%s байт, sha256=%s)", wav_path, total, digest.hexdigest()
    )
    _spawn(post_wav_and_transcribe(str(wav_path), filename))
    return web.Response(status=200, text="OK")


async def main() -> None:
    setup_logging()
    _check_ffmpeg()
    init_db()
    cleanup_inbox()

    app = web.Application(client_max_size=MAX_UPLOAD_BYTES)
    app.router.add_post("/upload", handle_esp32_upload)

    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, HTTP_HOST, HTTP_PORT).start()
    logger.info("HTTP-сервер для ESP32 слушает %s:%s", HTTP_HOST, HTTP_PORT)

    await bot.delete_webhook(drop_pending_updates=True)

    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop_event.set)
        except NotImplementedError:
            # Windows не умеет add_signal_handler — останавливаемся по Ctrl+C
            pass

    logger.info("Бот Telegram запущен")
    polling = asyncio.create_task(dp.start_polling(bot))
    stopper = asyncio.create_task(stop_event.wait())
    try:
        await asyncio.wait({polling, stopper}, return_when=asyncio.FIRST_COMPLETED)
    finally:
        logger.info("Остановка...")
        await dp.stop_polling()
        for task in list(_background_tasks):
            task.cancel()
        await runner.cleanup()
        await bot.session.close()
        logger.info("Остановлено")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
