import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    telegram_token: str
    groq_api_key: str
    groq_model: str = "llama-3.3-70b-versatile"
    groq_vision_model: str = "meta-llama/llama-4-scout-17b-16e-instruct"
    db_path: str = "storage/bot.sqlite3"
    archive_dir: str = "data/archive"
    drive_folder_id: str = ""
    google_api_key: str = ""
    max_context_docs: int = 8
    max_doc_chars: int = 2500
    max_upload_mb: int = 10


def load_settings(require_telegram: bool = True) -> Settings:
    def env(name: str, default: str = "") -> str:
        return os.getenv(name, default).strip()

    token = env("TELEGRAM_BOT_TOKEN")
    groq_key = env("GROQ_API_KEY")
    if require_telegram and not token:
        raise RuntimeError("Не задано TELEGRAM_BOT_TOKEN")
    if not groq_key:
        raise RuntimeError("Не задано GROQ_API_KEY")
    return Settings(
        telegram_token=token,
        groq_api_key=groq_key,
        groq_model=env("GROQ_MODEL", Settings.groq_model),
        groq_vision_model=env("GROQ_VISION_MODEL", Settings.groq_vision_model),
        db_path=env("DB_PATH", Settings.db_path),
        archive_dir=env("ARCHIVE_DIR", Settings.archive_dir),
        drive_folder_id=env("DRIVE_FOLDER_ID"),
        google_api_key=env("GOOGLE_API_KEY"),
    )
