"""OCR сканів: спершу vision-модель Groq, запасний варіант — Tesseract (ukr)."""
import asyncio
import io
import logging

from ..llm.groq_client import GroqClient, GroqError

log = logging.getLogger(__name__)
MIN_OCR_CHARS = 20


def tesseract_ocr(image_jpeg: bytes) -> str:
    try:
        import pytesseract
        from PIL import Image

        img = Image.open(io.BytesIO(image_jpeg)).convert("L")
        return pytesseract.image_to_string(img, lang="ukr+eng", config="--psm 6").strip()
    except Exception as e:
        log.warning("Tesseract не спрацював: %s", e)
        return ""


async def ocr_image(image_jpeg: bytes, groq: GroqClient | None) -> str:
    if groq is not None:
        try:
            text = await groq.vision_ocr(image_jpeg)
            if len(text.strip()) >= MIN_OCR_CHARS:
                return text
            log.warning("Vision-модель повернула замало тексту, пробую Tesseract")
        except GroqError as e:
            log.warning("Vision OCR не вдався (%s). Перевірте GROQ_VISION_MODEL. Пробую Tesseract", e)
    return await asyncio.to_thread(tesseract_ocr, image_jpeg)