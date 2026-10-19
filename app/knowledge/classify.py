"""Визначення типу документа і місця (scope) за назвою файлу та шапкою тексту.

Область дії часто вказана лише в тексті («Для мешканців біля річки»),
тому дивимось і на назву, і на початок документа.
"""
import re
from pathlib import Path

from .forest_map import DOC_TYPES, FOREST, FOREST_RE, find_areas, find_mittens

HEAD_CHARS = 400


def normalize_title(filename: str) -> str:
    name = Path(filename).stem
    name = re.sub(r"[_]+", " ", name)
    return re.sub(r"\s+", " ", name).strip()


def title_key(title: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", "", title.lower())).strip()


def detect_doc_type(title: str) -> str:
    t = title.lower()
    for key, pattern, _ in DOC_TYPES:
        if re.search(pattern, t):
            return key
    return "other:" + title_key(title)


def detect_scope(title: str, text: str) -> str | None:
    """Повертає ключ scope або None, якщо визначити однозначно не вдалося."""
    mittens = find_mittens(title)
    if mittens:
        return mittens[0] if len(mittens) == 1 else None
    areas = find_areas(title)
    if areas:
        return areas[0] if len(areas) == 1 else None

    head = text[:HEAD_CHARS].lower()
    if FOREST_RE.search(head):
        return FOREST
    mittens = find_mittens(head)
    if len(mittens) == 1:
        return mittens[0]
    areas = find_areas(head)
    if len(areas) == 1:
        return areas[0]
    return None


def classify(filename: str, text: str) -> tuple[str, str, str | None]:
    title = normalize_title(filename)
    return title, detect_doc_type(title), detect_scope(title, text)
