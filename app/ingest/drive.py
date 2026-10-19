"""Необов'язкове завантаження «Лісового архіву» з публічної теки Google Диска (Drive API v3)."""
import logging
import os
import re
from datetime import datetime
from pathlib import Path

import httpx

from .reader import SUPPORTED

log = logging.getLogger(__name__)
FILES_URL = "https://www.googleapis.com/drive/v3/files"


async def sync_drive_folder(folder_id: str, api_key: str, dest: Path) -> int:
    """Докачує файли, яких ще немає в dest. Повертає кількість нових файлів."""
    dest.mkdir(parents=True, exist_ok=True)
    new_files = 0
    async with httpx.AsyncClient(timeout=60.0) as http:
        page_token = None
        while True:
            params = {
                "q": f"'{folder_id}' in parents and trashed=false",
                "key": api_key,
                "fields": "nextPageToken,files(id,name,modifiedTime)",
                "pageSize": 1000,
            }
            if page_token:
                params["pageToken"] = page_token
            resp = await http.get(FILES_URL, params=params)
            resp.raise_for_status()
            payload = resp.json()
            for f in payload.get("files", []):
                name = re.sub(r"[\\/]", "_", f["name"])
                path = dest / name
                if path.suffix.lower() not in SUPPORTED or path.exists():
                    continue
                dl = await http.get(f"{FILES_URL}/{f['id']}", params={"alt": "media", "key": api_key})
                dl.raise_for_status()
                path.write_bytes(dl.content)
                try:
                    ts = datetime.fromisoformat(f["modifiedTime"].replace("Z", "+00:00")).timestamp()
                    os.utime(path, (ts, ts))
                except (KeyError, ValueError):
                    pass
                new_files += 1
            page_token = payload.get("nextPageToken")
            if not page_token:
                break
    log.info("З Google Диска завантажено нових файлів: %d", new_files)
    return new_files
