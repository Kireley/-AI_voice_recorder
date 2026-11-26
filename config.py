import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
INBOX_DIR = os.path.join(DATA_DIR, "inbox")
DB_PATH = os.path.join(DATA_DIR, "notes.db")
LEGACY_DB_PATH = os.path.join(BASE_DIR, "notes.db")

ENV_FILE = os.path.join(BASE_DIR, ".env")


def _load_env_file(path: str = ENV_FILE) -> None:
    """Подхватить KEY=VALUE из .env, не перетирая уже заданные переменные.

    Переменные окружения имеют приоритет над файлом — так удобнее запускать
    под systemd/Docker, где конфиг приходит извне.
    """
    try:
        with open(path, encoding="utf-8") as env_file:
            for line in env_file:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                os.environ.setdefault(key.strip(), value.strip().strip("\"'"))
    except FileNotFoundError:
        pass


_load_env_file()


def _require(name: str) -> str:
    """Обязательная переменная. Пустое значение — такая же ошибка, как отсутствие."""
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(
            f"Не задана переменная окружения {name}. "
            f"Скопируйте .env.example в .env и заполните значения."
        )
    return value


BOT_TOKEN = _require("VOICEAGENT_BOT_TOKEN")
YANDEX_API_KEY = _require("VOICEAGENT_YANDEX_API_KEY")
FOLDER_ID = _require("VOICEAGENT_FOLDER_ID")
UPLOAD_TOKEN = _require("VOICEAGENT_UPLOAD_TOKEN")
CHAT_ID = _require("VOICEAGENT_CHAT_ID")

PROXY_URL = os.getenv("VOICEAGENT_PROXY_URL") or None

HTTP_HOST = os.getenv("VOICEAGENT_HTTP_HOST", "").strip() or "0.0.0.0"
HTTP_PORT = int(os.getenv("VOICEAGENT_HTTP_PORT", "").strip() or "8000")

# Верхняя граница одного WAV-файла от ESP32 (8000 Гц mono 16 бит ≈ 16 КБ/сек,
# то есть 60 МБ — это больше часа записи).
MAX_UPLOAD_BYTES = 60 * 1024 * 1024

# Для 8000 Гц * 2 байта * 1 канал = 16000 байт/сек
BYTES_PER_SECOND = 16000
CHUNK_SECONDS = 28
CHUNK_SIZE = BYTES_PER_SECOND * CHUNK_SECONDS  # 448 000 байт





