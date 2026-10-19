"""Єдина точка читання файлу: PDF/DOCX/TXT → текст (зі сканами через OCR)."""
import asyncio
from dataclasses import dataclass
from pathlib import Path

from ..llm.groq_client import GroqClient
from . import parsers
from .ocr import ocr_image

SUPPORTED = {".pdf", ".docx", ".txt"}


class UnsupportedFile(Exception):
    pass


@dataclass
class ReadResult:
    text: str
    scanned: bool = False


async def read_file(filename: str, data: bytes, groq: GroqClient | None) -> ReadResult:
    ext = Path(filename).suffix.lower()
    if ext not in SUPPORTED:
        raise UnsupportedFile(ext)
    if ext == ".txt":
        return ReadResult(parsers.parse_txt(data))
    if ext == ".docx":
        return ReadResult(await asyncio.to_thread(parsers.parse_docx, data))

    pages, scan_idx = await asyncio.to_thread(parsers.parse_pdf, data)
    for i in scan_idx:
        image = await asyncio.to_thread(parsers.render_page_jpeg, data, i)
        pages[i] = parsers.clean(await ocr_image(image, groq))
    text = "\n\n".join(p for p in pages if p)
    return ReadResult(text, scanned=bool(scan_idx))
