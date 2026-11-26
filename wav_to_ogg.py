import asyncio
import logging
import shutil

logger = logging.getLogger(__name__)


async def wav_to_ogg_opus(wav_bytes: bytes) -> bytes:
    if shutil.which("ffmpeg") is None:
        raise RuntimeError("ffmpeg не найден в PATH — конвертация в OGG/Opus невозможна")

    process = await asyncio.create_subprocess_exec(
        "ffmpeg",
        "-hide_banner", "-loglevel", "error", "-nostdin",
        "-i", "pipe:0",          # читаем WAV из памяти
        "-c:a", "libopus",       # кодек Opus (обязателен для голосовых в Telegram)
        "-b:a", "32k",           # битрейт 32 кбит/с (отличное качество для голоса)
        "-vbr", "on",
        "-compression_level", "10",
        "-f", "ogg",             # контейнер OGG
        "pipe:1",                # отдаём результат в память
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )
    stdout, stderr = await process.communicate(input=wav_bytes)
    if process.returncode != 0:
        raise RuntimeError(f"Ошибка ffmpeg: {stderr.decode(errors='ignore')}")
    return stdout
