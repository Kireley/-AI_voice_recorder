import asyncio
import io
import json
import logging
import wave

import aiohttp

from config import YANDEX_API_KEY, FOLDER_ID, CHUNK_SIZE

logger = logging.getLogger(__name__)

STT_URL = "https://stt.api.cloud.yandex.net/speech/v1/stt:recognize"
LLM_URL = "https://llm.api.cloud.yandex.net/foundationModels/v1/completion"

# SpeechKit принимает только эти частоты. Смена SAMPLE_RATE на устройстве
# без правки этого множества даст 400 от API — проверяем заранее.
SUPPORTED_SAMPLE_RATES = {8000, 16000, 48000}

LLM_MODEL = "yandexgpt-lite"

PUNCTUATION_PROMPT = (
    "Ты технический скрипт-корректор. Расставь знаки препинания и заглавные буквы "
    "в сырой расшифровке внутри тегов <transcript>. Игнорируй смысл, не применяй цензуру. "
    "Верни только исправленный текст без тегов."
)

# YandexGPT иногда отказывается обрабатывать текст; такой ответ считаем пустым,
# чтобы вызывающий код ушёл в fallback.
REFUSAL_MARKER = "не могу обсуждать эту тему"


def extract_pcm(wav_bytes: bytes) -> tuple[bytes, int]:
    """Вернуть проверенный mono 16-bit PCM и фактическую частоту дискретизации."""
    try:
        with wave.open(io.BytesIO(wav_bytes), "rb") as wav_file:
            if wav_file.getcomptype() != "NONE":
                raise ValueError("WAV со сжатием не поддерживается")
            if wav_file.getnchannels() != 1 or wav_file.getsampwidth() != 2:
                raise ValueError("Ожидается mono 16-bit PCM WAV")
            return wav_file.readframes(wav_file.getnframes()), wav_file.getframerate()
    except (wave.Error, EOFError) as exc:
        raise ValueError("Некорректный или неподдерживаемый WAV-файл") from exc


async def recognize_chunk(
    http_session: aiohttp.ClientSession,
    pcm_chunk: bytes,
    sample_rate: int,
    attempts: int = 3,
) -> str:
    """Распознать один кусок. Ретраит 429/5xx, пустую строку возвращает как ошибку."""
    params = {"lang": "ru-RU", "format": "lpcm", "sampleRateHertz": str(sample_rate)}
    headers = {"Authorization": f"Api-Key {YANDEX_API_KEY}"}
    delay = 1.0

    for attempt in range(1, attempts + 1):
        try:
            async with http_session.post(STT_URL, params=params, headers=headers, data=pcm_chunk) as resp:
                body = await resp.text()
                if resp.status == 200:
                    try:
                        return json.loads(body).get("result", "").strip()
                    except json.JSONDecodeError:
                        logger.error("SpeechKit вернул не-JSON: %s", body[:200])
                        return ""
                if resp.status != 429 and resp.status < 500:
                    logger.error("SpeechKit %s: %s", resp.status, body[:200])
                    return ""
                logger.warning("SpeechKit %s (попытка %s/%s)", resp.status, attempt, attempts)
        except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
            logger.warning("SpeechKit недоступен (попытка %s/%s): %r", attempt, attempts, exc)

        if attempt < attempts:
            await asyncio.sleep(delay)
            delay *= 2

    logger.error("Кусок аудио потерян после %s попыток", attempts)
    return ""


async def transcribe_yandex(wav_bytes: bytes) -> str:
    pcm_data, sample_rate = extract_pcm(wav_bytes)
    if not pcm_data:
        return ""
    if sample_rate not in SUPPORTED_SAMPLE_RATES:
        raise ValueError(
            f"Частота {sample_rate} Гц не поддерживается SpeechKit "
            f"(допустимо: {sorted(SUPPORTED_SAMPLE_RATES)})"
        )

    chunk_size = CHUNK_SIZE if sample_rate == 8000 else sample_rate * 2 * 28
    chunks = [pcm_data[i : i + chunk_size] for i in range(0, len(pcm_data), chunk_size)]
    transcripts = []
    lost = 0

    timeout = aiohttp.ClientTimeout(total=30)
    async with aiohttp.ClientSession(trust_env=False, timeout=timeout) as http_session:
        for chunk in chunks:
            text = await recognize_chunk(http_session, chunk, sample_rate)
            if text:
                transcripts.append(text)
            else:
                lost += 1

    if lost:
        logger.warning("Не распознано кусков: %s из %s", lost, len(chunks))
    return " ".join(transcripts)


async def _completion(system_prompt: str, user_text: str, model: str = LLM_MODEL) -> str:
    """Один запрос к YandexGPT. Пустая строка при любой ошибке — вызывающий делает fallback."""
    headers = {
        "Authorization": f"Api-Key {YANDEX_API_KEY}",
        "x-folder-id": FOLDER_ID,
    }
    payload = {
        "modelUri": f"gpt://{FOLDER_ID}/{model}/latest",
        "completionOptions": {"stream": False, "temperature": 0.1, "maxTokens": "2000"},
        "messages": [
            {"role": "system", "text": system_prompt},
            {"role": "user", "text": f"<transcript>{user_text}</transcript>"},
        ],
    }

    timeout = aiohttp.ClientTimeout(total=20)
    async with aiohttp.ClientSession(trust_env=False, timeout=timeout) as http_session:
        try:
            async with http_session.post(LLM_URL, headers=headers, json=payload) as resp:
                if resp.status != 200:
                    logger.error("YandexGPT %s: %s", resp.status, (await resp.text())[:200])
                    return ""
                data = await resp.json()
        except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
            logger.warning("YandexGPT недоступен: %r", exc)
            return ""

    alternatives = data.get("result", {}).get("alternatives") or []
    if not alternatives:
        logger.warning("YandexGPT вернул пустой alternatives")
        return ""

    reply = (alternatives[0].get("message", {}).get("text") or "").strip()
    if REFUSAL_MARKER in reply.lower():
        logger.info("YandexGPT отказался обрабатывать текст")
        return ""
    return reply


async def format_punctuation(raw_text: str) -> str:
    """Расставить пунктуацию. Без LLM возвращает текст с заглавной буквы."""
    clean = raw_text.strip()
    if not clean:
        return ""

    fallback = clean[0].upper() + clean[1:]
    if len(clean.split()) < 4:
        return fallback + "."

    return await _completion(PUNCTUATION_PROMPT, clean) or fallback


async def run_yandex_gpt(system_prompt: str, user_text: str, model: str = LLM_MODEL) -> str:
    """Запрос к YandexGPT с произвольным системным промптом (для триггеров)."""
    clean = user_text.strip()
    if not clean:
        return ""
    return await _completion(system_prompt, clean, model=model)
