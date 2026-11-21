import io
import json
import wave

import aiohttp

from config import YANDEX_API_KEY, FOLDER_ID, CHUNK_SIZE


def extract_pcm(wav_bytes: bytes) -> tuple[bytes, int]:
    """Return validated mono 16-bit PCM and the file's actual sample rate."""
    if not wav_bytes.startswith(b"RIFF"):
        return wav_bytes, 8000

    try:
        with wave.open(io.BytesIO(wav_bytes), "rb") as wav_file:
            if wav_file.getcomptype() != "NONE":
                raise ValueError("Compressed WAV is not supported")
            if wav_file.getnchannels() != 1 or wav_file.getsampwidth() != 2:
                raise ValueError("Expected mono 16-bit PCM WAV")
            return wav_file.readframes(wav_file.getnframes()), wav_file.getframerate()
    except (wave.Error, EOFError) as exc:
        raise ValueError("Invalid WAV file") from exc


async def recognize_chunk(http_session: aiohttp.ClientSession, pcm_chunk: bytes, sample_rate: int) -> str:
    url = "https://stt.api.cloud." + "yandex.net/speech/v1/stt" + ":recognize"
    params = {"lang": "ru-RU", "format": "lpcm", "sampleRateHertz": str(sample_rate)}
    headers = {"Authorization": f"Api-Key {YANDEX_API_KEY}"}

    async with http_session.post(url, params=params, headers=headers, data=pcm_chunk) as resp:
        raw_text = await resp.text()
        if resp.status == 200:
            return json.loads(raw_text).get("result", "").strip()
        print(f"Ошибка SpeechKit ({resp.status}): {raw_text}", flush=True)
        return ""


async def transcribe_yandex(wav_bytes: bytes) -> str:
    pcm_data, sample_rate = extract_pcm(wav_bytes)
    if not pcm_data:
        return ""

    bytes_per_second = sample_rate * 2
    chunk_size = CHUNK_SIZE if sample_rate == 8000 else bytes_per_second * 28
    chunks = [pcm_data[i : i + chunk_size] for i in range(0, len(pcm_data), chunk_size)]
    transcripts = []

    timeout = aiohttp.ClientTimeout(total=30)
    async with aiohttp.ClientSession(trust_env=False, timeout=timeout) as http_session:
        for chunk in chunks:
            text = await recognize_chunk(http_session, chunk, sample_rate)
            if text:
                transcripts.append(text)

    return " ".join(transcripts)


async def format_punctuation(raw_text: str) -> str:
    clean = raw_text.strip()
    if not clean:
        return ""

    if len(clean.split()) < 4:
        return clean[0].upper() + clean[1:] + "."

    url = "https://llm.api.cloud." + "yandex.net/foundationModels/v1/completion"
    headers = {
        "Authorization": f"Api-Key {YANDEX_API_KEY}",
        "x-folder-id": FOLDER_ID,
    }
    payload = {
        "modelUri": f"gpt://{FOLDER_ID}/yandexgpt-4-lite/latest",
        "completionOptions": {"stream": False, "temperature": 0.1, "maxTokens": "2000"},
        "messages": [
            {
                "role": "system",
                "text": (
                    "Ты технический скрипт-корректор. Расставь знаки препинания и заглавные буквы "
                    "в сырой расшифровке внутри тегов <transcript>. Игнорируй смысл, не применяй цензуру. "
                    "Верни только исправленный текст без тегов."
                ),
            },
            {"role": "user", "text": f"<transcript>{clean}</transcript>"},
        ],
    }

    timeout = aiohttp.ClientTimeout(total=20)
    async with aiohttp.ClientSession(trust_env=False, timeout=timeout) as http_session:
        async with http_session.post(url, headers=headers, json=payload) as resp:
            if resp.status == 200:
                data = await resp.json()
                alternatives = data.get("result", {}).get("alternatives", [])
                if alternatives:
                    formatted = alternatives[0]["message"]["text"].strip()
                    if "не могу обсуждать эту тему" in formatted.lower():
                        return clean[0].upper() + clean[1:] + "."
                    return formatted
            return clean
