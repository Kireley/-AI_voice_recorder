import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
INBOX_DIR = os.path.join(DATA_DIR, "inbox")
DB_PATH = os.path.join(DATA_DIR, "notes.db")
LEGACY_DB_PATH = os.path.join(BASE_DIR, "notes.db")

BOT_TOKEN = os.environ["VOICEAGENT_BOT_TOKEN"]
YANDEX_API_KEY = os.environ["VOICEAGENT_YANDEX_API_KEY"]
FOLDER_ID = os.environ["VOICEAGENT_FOLDER_ID"]
UPLOAD_TOKEN = os.environ["VOICEAGENT_UPLOAD_TOKEN"]

CHAT_ID = os.environ["VOICEAGENT_CHAT_ID"]
PROXY_URL = os.getenv("VOICEAGENT_PROXY_URL")

# Для 8000 Гц * 2 байта * 1 канал = 16000 байт/сек
BYTES_PER_SECOND = 16000
CHUNK_SECONDS = 28
CHUNK_SIZE = BYTES_PER_SECOND * CHUNK_SECONDS  # 448 000 байт





