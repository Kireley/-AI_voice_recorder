import asyncio
import hashlib
import os
import secrets
import traceback
import uuid
from pathlib import Path

from aiohttp import web
from aiogram import Bot, Dispatcher
from aiogram.types import BufferedInputFile
from aiogram.client.session.aiohttp import AiohttpSession

from config import BOT_TOKEN, CHAT_ID, INBOX_DIR, PROXY_URL, UPLOAD_TOKEN
from db import init_db
from yandex_api import transcribe_yandex
from bot_handlers import router, process_recognized_text
from wav_to_ogg import wav_to_ogg_opus
session = AiohttpSession(proxy=PROXY_URL, timeout=180) if PROXY_URL else None
bot = Bot(token=BOT_TOKEN, session=session)
dp = Dispatcher()
dp.include_router(router)


async def post_wav_and_transcribe(wav_path: str, filename: str = "record.wav"):
    try:
        wav_bytes = await asyncio.to_thread(Path(wav_path).read_bytes)
        print(f"Получен файл {filename} ({len(wav_bytes)} байт)...", flush=True)

        # 1. Распознаём исходный WAV через Яндекс (быстро и без прокси)
        raw_text = await transcribe_yandex(wav_bytes)

        # 2. Конвертируем WAV в лёгкий OGG Opus в памяти

        ogg_bytes = await wav_to_ogg_opus(wav_bytes)
        base_name, _ = os.path.splitext(filename)
        ogg_filename = f"{base_name}.ogg"
        print(f"Сжато в OGG: {len(ogg_bytes)} байт, шлём голосовое в Telegram...", flush=True)


        # 3. Отправляем как голосовое сообщение (send_voice) с повторами
        sent_voice_msg = None
        retry_delays = [5, 15, 30]
        for attempt in range(len(retry_delays) + 1):
            try:
                input_file = BufferedInputFile(ogg_bytes, filename=ogg_filename)
                sent_voice_msg = await bot.send_voice(
                    chat_id=CHAT_ID,
                    voice=input_file,
                    request_timeout=60
                )
                break
            except Exception as net_err:
                if attempt == len(retry_delays):
                    print(f"Не удалось отправить голосовое: {net_err}", flush=True)
                    break
                delay = retry_delays[attempt]
                print(f"Повтор отправки в Telegram через {delay}с: {net_err}", flush=True)
                await asyncio.sleep(delay)

        # 4. Передаём сообщение с голосовым в ваш обработчик текста
        if sent_voice_msg:
            await process_recognized_text(bot, sent_voice_msg, raw_text)
        else:
            await bot.send_message(chat_id=CHAT_ID, text=f"⚠️ Голосовое не загрузилось, но текст распознан:\n\n{raw_text}")
            raise RuntimeError("Voice delivery failed; source WAV was kept for retry")

        await asyncio.to_thread(Path(wav_path).unlink, missing_ok=True)
        print("Обработка завершена!", flush=True)
    except Exception as e:
        print(f"ОШИБКА обработки {wav_path}: {repr(e)}", flush=True)
        traceback.print_exc()



async def handle_esp32_upload(request: web.Request) -> web.Response:
    if not secrets.compare_digest(request.headers.get("X-Upload-Token", ""), UPLOAD_TOKEN):
        return web.Response(status=401, text="Unauthorized")

    filename = os.path.basename(request.headers.get("X-Filename", "esp32_rec.wav"))
    if not filename.lower().endswith(".wav"):
        return web.Response(status=400, text="WAV file required")
    if request.content_length == 0:
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
                output.write(chunk)
                digest.update(chunk)
                total += len(chunk)
        if total == 0:
            temp_path.unlink(missing_ok=True)
            return web.Response(status=400, text="Empty body")
        temp_path.replace(wav_path)
    except (ConnectionResetError, asyncio.CancelledError) as exc:
        temp_path.unlink(missing_ok=True)
        print(f"ESP32 разорвала соединение во время передачи: {exc}", flush=True)
        return web.Response(status=499, text="Client closed request")
    except Exception:
        temp_path.unlink(missing_ok=True)
        raise

    print(f"Файл сохранён: {wav_path} ({total} байт, sha256={digest.hexdigest()})", flush=True)
    asyncio.create_task(post_wav_and_transcribe(str(wav_path), filename))
    return web.Response(status=200, text="OK")



async def main():
    init_db()

    app = web.Application(client_max_size=60 * 1024 * 1024)
    app.router.add_post("/upload", handle_esp32_upload)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", 8000)
    await site.start()

    print("HTTP-сервер для ESP32 слушает порт 8000, бот Telegram запущен...", flush=True)
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
