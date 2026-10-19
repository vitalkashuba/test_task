"""Мінімальний асинхронний клієнт Groq (OpenAI-сумісний API) з ретраями на 429/5xx."""
import asyncio
import base64
import logging

import httpx

log = logging.getLogger(__name__)
API_URL = "https://api.groq.com/openai/v1/chat/completions"

OCR_PROMPT = (
    "Це скан сторінки українською мовою. Перепиши весь текст зі сторінки дослівно, "
    "зберігаючи заголовки, абзаци й списки. Усі числа, назви та імена переписуй точно. "
    "Фонову текстуру, плями й тіні ігноруй. Виведи лише текст, без коментарів."
)


class GroqError(Exception):
    pass


class GroqClient:
    def __init__(self, api_key: str, model: str, vision_model: str):
        self.model = model
        self.vision_model = vision_model
        self._http = httpx.AsyncClient(
            timeout=httpx.Timeout(90.0),
            headers={"Authorization": f"Bearer {api_key}"},
        )

    async def aclose(self) -> None:
        await self._http.aclose()

    async def _post(self, payload: dict, max_wait: float) -> str:
        last_error = "невідома помилка"
        for attempt in range(5):
            try:
                resp = await self._http.post(API_URL, json=payload)
            except httpx.HTTPError as e:
                last_error = f"мережа: {e}"
                await asyncio.sleep(min(2 ** attempt, max_wait))
                continue
            if resp.status_code == 200:
                try:
                    return resp.json()["choices"][0]["message"]["content"] or ""
                except (KeyError, IndexError, ValueError) as e:
                    raise GroqError(f"неочікувана відповідь Groq: {e}") from e
            if resp.status_code in (429, 500, 502, 503, 504):
                try:
                    wait = float(resp.headers.get("retry-after", 2 ** attempt))
                except ValueError:
                    wait = 2 ** attempt
                last_error = f"HTTP {resp.status_code}"
                log.warning("Groq %s, чекаю %.1f с", resp.status_code, wait)
                await asyncio.sleep(min(wait, max_wait))
                continue
            raise GroqError(f"HTTP {resp.status_code}: {resp.text[:300]}")
        raise GroqError(f"Groq недоступний ({last_error})")

    async def chat(
        self,
        messages: list[dict],
        *,
        json_mode: bool = False,
        temperature: float = 0.1,
        max_tokens: int = 900,
        max_wait: float = 20.0,
    ) -> str:
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        return await self._post(payload, max_wait)

    async def vision_ocr(self, image_jpeg: bytes, max_wait: float = 60.0) -> str:
        b64 = base64.b64encode(image_jpeg).decode()
        payload = {
            "model": self.vision_model,
            "temperature": 0.1,
            "max_tokens": 4000,
            "reasoning_effort": "none",
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": OCR_PROMPT},
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
                    ],
                }
            ],
        }
        try:
            text = await self._post(payload, max_wait)
        except GroqError as e:
            if "HTTP 400" in str(e) and "reasoning" in str(e).lower():
                payload.pop("reasoning_effort")
                text = await self._post(payload, max_wait)
            else:
                raise
        if "</think>" in text:
            text = text.split("</think>", 1)[1]
        text = text.strip()
        if text.startswith("```"):
            text = text.strip("`").removeprefix("text").strip()
        return text
