"""Завантаження «Лісового архіву» в базу при старті (один раз, результат кешується)."""
import logging
from datetime import datetime, timezone
from pathlib import Path

from ..config import Settings
from ..knowledge.classify import classify
from ..knowledge.forest_map import FOREST
from ..knowledge.store import Store
from ..llm.groq_client import GroqClient
from .drive import sync_drive_folder
from .reader import SUPPORTED, read_file

log = logging.getLogger(__name__)


async def load_archive(store: Store, groq: GroqClient | None, settings: Settings) -> int:
    folder = Path(settings.archive_dir)
    if settings.drive_folder_id and settings.google_api_key:
        try:
            await sync_drive_folder(settings.drive_folder_id, settings.google_api_key, folder)
        except Exception as e:
            log.warning("Не вдалося синхронізувати Google Диск (%s), беру локальну копію", e)

    files = sorted(p for p in folder.glob("*") if p.suffix.lower() in SUPPORTED)
    added = 0
    for path in files:
        if store.has_source_key(path.name):
            continue
        try:
            result = await read_file(path.name, path.read_bytes(), groq)
        except Exception as e:
            log.error("Не вдалося прочитати %s: %s", path.name, e)
            continue
        if len(result.text) < 30:
            log.error("Порожній текст після читання: %s (спробую при наступному запуску)", path.name)
            continue
        title, doc_type, scope = classify(path.name, result.text)
        if scope is None:
            log.warning("Не вдалося визначити місце для %s — вважаю загальним", path.name)
            scope = FOREST
        mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat(timespec="seconds")
        store.add_document(
            title=title, doc_type=doc_type, scope=scope, text=result.text,
            source="archive", source_key=path.name, uploaded_at=mtime,
        )
        added += 1
        log.info("Архів: %s → %s / %s%s", path.name, doc_type, scope, " (скан)" if result.scanned else "")
    log.info("Архів готовий: нових документів %d, усього в базі %d", added, store.count())
    return added
