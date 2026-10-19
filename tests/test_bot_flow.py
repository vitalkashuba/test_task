"""Прогін діалогів через справжній Dispatcher aiogram; Telegram і Groq підмінені."""
import asyncio
import io
import time

from aiogram import Bot, Dispatcher
from aiogram.client.bot import Bot as BotCls
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import Update

from app.bot import handlers
from app.config import Settings
from app.knowledge.store import Store
from app.llm.answer import Answer

USER = {"id": 42, "is_bot": False, "first_name": "Test"}
CHAT = {"id": 42, "type": "private"}


class Harness:
    def __init__(self, monkeypatch, files=None):
        self.sent: list = []
        self.files = files or {}
        monkeypatch.setattr(BotCls, "__call__", self._call)
        monkeypatch.setattr(BotCls, "download", self._download)
        self.store = Store(":memory:")
        self.bot = Bot("123:ABC")
        self.settings = Settings(telegram_token="x", groq_api_key="x")
        self.dp = Dispatcher(storage=MemoryStorage(), store=self.store, groq=object(), settings=self.settings)
        handlers.router._parent_router = None  # у тестах диспетчер створюється щоразу
        self.dp.include_router(handlers.router)
        self.n = 0

    async def _call(self, method, request_timeout=None):
        self.sent.append(method)
        return True

    async def _download(self, file, *a, **kw):
        return io.BytesIO(self.files[file])

    def texts(self):
        return [getattr(m, "text", "") or "" for m in self.sent]

    async def feed(self, **fields):
        self.n += 1
        msg = {"message_id": self.n, "date": int(time.time()), "chat": CHAT, "from": USER, **fields}
        upd = Update.model_validate({"update_id": self.n, "message": msg}, context={"bot": self.bot})
        await self.dp.feed_update(self.bot, upd)

    async def click(self, data):
        self.n += 1
        cb = {"id": str(self.n), "from": USER, "chat_instance": "c", "data": data,
              "message": {"message_id": 1, "date": int(time.time()), "chat": CHAT}}
        upd = Update.model_validate({"update_id": self.n, "callback_query": cb}, context={"bot": self.bot})
        await self.dp.feed_update(self.bot, upd)


def doc(name, file_id):
    return {"document": {"file_id": file_id, "file_unique_id": file_id, "file_name": name, "file_size": 200}}


def test_upload_flow_asks_name_once_then_replaces(monkeypatch):
    old = "Членські внески рукавички Під дубом.txt"
    h = Harness(monkeypatch, files={
        "f1": "Внесок — 4 жолуді на місяць. Здавати до 10 числа щомісяця, Кабанові в кошик.".encode(),
        "f2": "Тепер внесок — 5 жолудів на місяць. Здавати до 12 числа щомісяця.".encode(),
    })

    async def run():
        await h.feed(**doc(old, "f1"))                     # перше надсилання → питаємо ім'я
        assert any("як вас звати" in t for t in h.texts())
        await h.feed(text="Скарбник Борсук")               # ім'я збережено, документ оброблено
        assert h.store.get_user_name(42) == "Скарбник Борсук"
        assert any("Під дубом" in t and "Все вірно" in t for t in h.texts())
        await h.click("doc:save")
        assert h.store.count() == 1

        h.sent.clear()
        await h.feed(**doc("Нові внески Під дубом.txt", "f2"))   # ім'я вдруге не питаємо
        assert not any("як вас звати" in t for t in h.texts())
        assert any("замінить" in t for t in h.texts())
        await h.click("doc:save")

    asyncio.run(run())
    active = h.store.active_in_scopes(["m_dub"])
    assert len(active) == 1 and "5 жолудів" in active[0].text
    assert active[0].author_name == "Скарбник Борсук"


def test_unknown_place_asks_author_and_cancel_saves_nothing(monkeypatch):
    h = Harness(monkeypatch, files={"f": "Порада без адресата, написана просто так, для прикладу.".encode()})
    h.store.set_user_name(42, "Їжак")

    async def run():
        await h.feed(**doc("Нова порада.txt", "f"))
        assert any("для якого місця" in t for t in h.texts())
        await h.click("doc:cancel")

    asyncio.run(run())
    assert h.store.count() == 0


def test_unsupported_and_group_messages(monkeypatch):
    h = Harness(monkeypatch)

    async def run():
        await h.feed(**doc("table.xlsx", "x"))
        assert any("PDF, Word" in t for t in h.texts())
        h.sent.clear()
        # груповий чат ігнорується
        h.n += 1
        msg = {"message_id": 1, "date": int(time.time()), "chat": {"id": -1, "type": "group", "title": "g"},
               "from": USER, "text": "Які внески?"}
        await h.dp.feed_update(h.bot, Update.model_validate({"update_id": h.n, "message": msg}, context={"bot": h.bot}))
        assert not h.sent

    asyncio.run(run())


def test_question_pipeline_and_place_followup(monkeypatch):
    h = Harness(monkeypatch)
    h.store.add_document(title="Членські внески рукавички Під дубом", doc_type="fees", scope="m_dub",
                         source="archive", text="Внесок — 4 жолуді на місяць.")
    seen = {}

    async def fake_generate(groq, question, docs, max_chars):
        seen["q"], seen["docs"] = question, docs
        return Answer(found=True, text="4 жолуді на місяць [1].", sources=[(1, docs[0])])

    monkeypatch.setattr(handlers, "generate_answer", fake_generate)

    async def run():
        await h.feed(text="Які внески?")                   # без місця → уточнюємо
        assert any("Про яке місце" in t for t in h.texts())
        await h.feed(text="Під дубом")                     # відповідь на уточнення
        out = h.texts()[-1]
        assert "4 жолуді" in out and "Джерела:" in out and "Лісовий архів" in out

    asyncio.run(run())
    assert "Які внески?" in seen["q"] and "Під дубом" in seen["q"]


def test_not_found_is_honest(monkeypatch):
    h = Harness(monkeypatch)
    h.store.add_document(title="Що робити при пожежі", doc_type="other:x", scope="forest",
                         source="archive", text="Довгий крик означає пожежу.")

    async def fake_generate(*a, **kw):
        return Answer(found=False)

    monkeypatch.setattr(handlers, "generate_answer", fake_generate)

    async def run():
        await h.feed(text="Що робити при пожежі?")
        assert "не знайшов" in h.texts()[-1]

    asyncio.run(run())


def test_mydocs_delete(monkeypatch):
    h = Harness(monkeypatch)
    did = h.store.add_document(title="Моя порада", doc_type="other:x", scope="forest", source="user",
                               author_name="А", author_tg_id=42, text="текст порад")

    async def run():
        await h.feed(text="/mydocs")
        await h.click(f"del:{did}")
        await h.click(f"delyes:{did}")

    asyncio.run(run())
    assert h.store.get(did).is_active == 0
