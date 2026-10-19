"""Перевірка без Telegram: python -m app.cli "Які внески в рукавичці Під дубом?" """
import asyncio
import sys

from .config import load_settings
from .ingest.archive import load_archive
from .knowledge.scope import parse_place
from .knowledge.search import retrieve
from .knowledge.store import Store
from .llm.answer import generate_answer, source_line
from .llm.groq_client import GroqClient


async def main(question: str) -> None:
    settings = load_settings(require_telegram=False)
    store = Store(settings.db_path)
    groq = GroqClient(settings.groq_api_key, settings.groq_model, settings.groq_vision_model)
    try:
        await load_archive(store, groq, settings)
        found = retrieve(store, question, parse_place(question), settings.max_context_docs)
        print(f"[статус: {found.status}; документи: {[d.title for d in found.docs]}]")
        if found.status != "ok":
            return
        answer = await generate_answer(groq, question, found.docs, settings.max_doc_chars)
        if not answer.found:
            print("В наданих порадах я цього не знайшов.")
            return
        print(answer.text, "\n\nДжерела:")
        for n, d in answer.sources:
            print(source_line(n, d))
    finally:
        await groq.aclose()


if __name__ == "__main__":
    asyncio.run(main(" ".join(sys.argv[1:])))
