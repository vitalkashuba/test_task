import logging
import re
import time
from pathlib import Path

from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from ..config import Settings
from ..ingest.reader import SUPPORTED, read_file
from ..knowledge.classify import classify
from ..knowledge.forest_map import ALL_SCOPES, DOC_TYPE_LABELS, scope_label
from ..knowledge.replace import plan_replacement
from ..knowledge.scope import parse_place
from ..knowledge.search import retrieve
from ..knowledge.store import Store
from ..llm.answer import fmt_date, generate_answer, source_line
from ..llm.groq_client import GroqClient, GroqError
from . import texts

log = logging.getLogger(__name__)

router = Router()
router.message.filter(F.chat.type == "private")  # лише особисті повідомлення
router.callback_query.filter(F.message.chat.type == "private")

PENDING_Q: dict[int, tuple[str, float]] = {}  # питання, що чекає на уточнення місця
PENDING_TTL = 600
TG_LIMIT = 4000

# Відповіді на «про яке місце питаєте?», що означають «неважливо / всюди»
GENERAL_RE = re.compile(
    r"\b(взагалі|всюди|будь-де|не\s+важливо|все\s+одно|весь\s+ліс|всього\s+лісу)\b"
)
GENERAL_HINT = "\n\nМожу уточнити для вашої рукавички чи частини лісу — просто назвіть її."


class Upload(StatesGroup):
    asking_name = State()
    confirming = State()


# ---------------------------------------------------------------- команди

@router.message(CommandStart())
@router.message(Command("help"))
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(texts.START)


@router.message(Command("mydocs"))
async def cmd_mydocs(message: Message, store: Store):
    docs = store.user_docs(message.from_user.id)
    if not docs:
        await message.answer(texts.NO_MYDOCS)
        return
    kb = InlineKeyboardBuilder()
    for d in docs[:20]:
        kb.button(text=f"🗑 {d.title[:40]}", callback_data=f"del:{d.id}")
    kb.adjust(1)
    await message.answer(texts.MYDOCS_HEAD, reply_markup=kb.as_markup())


@router.callback_query(F.data.startswith("del:"))
async def ask_delete(cb: CallbackQuery, store: Store):
    doc = store.get(int(cb.data.split(":")[1]))
    if not doc or doc.author_tg_id != cb.from_user.id or not doc.is_active:
        await cb.answer("Документ не знайдено", show_alert=True)
        return
    kb = InlineKeyboardBuilder()
    kb.button(text="Так, видалити", callback_data=f"delyes:{doc.id}")
    kb.button(text="Скасувати", callback_data="delno")
    kb.adjust(2)
    await cb.message.answer(
        f"Видалити «{doc.title}»? Звірі більше не бачитимуть цю пораду.", reply_markup=kb.as_markup()
    )
    await cb.answer()


@router.callback_query(F.data.startswith("delyes:"))
async def do_delete(cb: CallbackQuery, store: Store):
    ok = store.deactivate(int(cb.data.split(":")[1]), cb.from_user.id)
    await cb.message.edit_text("🗑 Видалено." if ok else "Документ уже видалено або не ваш.")
    await cb.answer()


@router.callback_query(F.data == "delno")
async def no_delete(cb: CallbackQuery):
    await cb.message.edit_text("Гаразд, лишаю.")
    await cb.answer()


# ---------------------------------------------------------------- завантаження документів

def scope_keyboard() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for key in ALL_SCOPES:
        label = "Весь ліс" if key == "forest" else scope_label(key).capitalize()
        kb.button(text=label, callback_data=f"scope:{key}")
    kb.button(text="❌ Скасувати", callback_data="doc:cancel")
    kb.adjust(2)
    return kb.as_markup()


def draft_view(store: Store, draft: dict) -> tuple[str, InlineKeyboardMarkup]:
    if not draft["scope"]:
        return f"📄 «{draft['title']}»\n\n{texts.NO_SCOPE}", scope_keyboard()

    type_label = DOC_TYPE_LABELS.get(draft["doc_type"], "Інший документ")
    lines = [
        f"📄 «{draft['title']}»",
        f"Тип: {type_label}",
        f"Для: {scope_label(draft['scope'])}",
        f"Автор: {draft['author_name']}",
        "",
        "🔎 Це скан, я прочитав його так:" if draft["scanned"] else "Початок тексту:",
        "«" + draft["text"][:300].replace("\n", " ") + ("…" if len(draft["text"]) > 300 else "") + "»",
        "",
    ]
    plan = plan_replacement(store, draft["doc_type"], draft["scope"], draft["title"])
    kb = InlineKeyboardBuilder()
    if plan.mode == "auto":
        old = "; ".join(f"«{d.title}» ({fmt_date(d.uploaded_at)})" for d in plan.docs)
        lines.append(f"🔁 Це замінить попередню пораду: {old}. Звірі бачитимуть лише нову.")
        kb.button(text="✅ Зберегти й замінити", callback_data="doc:save")
    elif plan.mode == "ask":
        old = "; ".join(f"«{d.title}»" for d in plan.docs)
        lines.append(f"Схоже на вже збережене: {old}. Це новіша версія того самого документа?")
        kb.button(text="🔁 Так, замінити", callback_data="doc:replace")
        kb.button(text="➕ Ні, окремий документ", callback_data="doc:separate")
    else:
        lines.append("Все вірно?")
        kb.button(text="✅ Зберегти", callback_data="doc:save")
    kb.button(text="✏️ Змінити місце", callback_data="doc:chscope")
    kb.button(text="❌ Скасувати", callback_data="doc:cancel")
    kb.adjust(1)
    return "\n".join(lines), kb.as_markup()


async def process_upload(
    message: Message, state: FSMContext, bot: Bot, store: Store, groq: GroqClient,
    file_id: str, filename: str, author_name: str,
):
    await message.answer(texts.READING)
    try:
        data = (await bot.download(file_id)).read()
        result = await read_file(filename, data, groq)
    except Exception:
        log.exception("Не вдалося прочитати %s", filename)
        await message.answer(texts.READ_FAILED)
        return
    if len(result.text) < 30:
        await message.answer(texts.READ_EMPTY)
        return
    title, doc_type, scope = classify(filename, result.text)
    draft = {
        "title": title, "doc_type": doc_type, "scope": scope, "text": result.text,
        "scanned": result.scanned, "author_name": author_name,
    }
    await state.set_state(Upload.confirming)
    await state.update_data(draft=draft)
    text, markup = draft_view(store, draft)
    await message.answer(text, reply_markup=markup)


@router.message(F.document)
async def on_document(
    message: Message, state: FSMContext, bot: Bot, store: Store, groq: GroqClient, settings: Settings
):
    doc = message.document
    name = doc.file_name or "document"
    ext = Path(name).suffix.lower()
    if ext == ".doc":
        await message.answer(texts.OLD_DOC)
        return
    if ext not in SUPPORTED:
        await message.answer(texts.UNSUPPORTED_DOC)
        return
    if doc.file_size and doc.file_size > settings.max_upload_mb * 1024 * 1024:
        await message.answer(texts.TOO_BIG.format(mb=settings.max_upload_mb))
        return
    await state.clear()
    author = store.get_user_name(message.from_user.id)
    if not author:  # справжнє ім'я питаємо один раз — під час першого надсилання
        await state.set_state(Upload.asking_name)
        await state.update_data(pending={"file_id": doc.file_id, "filename": name})
        await message.answer(texts.ASK_NAME)
        return
    await process_upload(message, state, bot, store, groq, doc.file_id, name, author)


@router.message(Upload.asking_name, F.text)
async def on_name(message: Message, state: FSMContext, bot: Bot, store: Store, groq: GroqClient):
    name = " ".join(message.text.split())
    if not 2 <= len(name) <= 60 or name.startswith("/"):
        await message.answer(texts.BAD_NAME)
        return
    store.set_user_name(message.from_user.id, name)
    pending = (await state.get_data()).get("pending")
    await state.clear()
    await message.answer(texts.NAME_SAVED.format(name=name))
    if pending:
        await process_upload(
            message, state, bot, store, groq, pending["file_id"], pending["filename"], name
        )


async def _draft_or_stale(cb: CallbackQuery, state: FSMContext) -> dict | None:
    draft = (await state.get_data()).get("draft")
    if not draft:
        await cb.answer(texts.STALE, show_alert=True)
    return draft


@router.callback_query(F.data.startswith("scope:"))
async def pick_scope(cb: CallbackQuery, state: FSMContext, store: Store):
    draft = await _draft_or_stale(cb, state)
    if not draft:
        return
    key = cb.data.split(":", 1)[1]
    if key not in ALL_SCOPES:
        await cb.answer()
        return
    draft["scope"] = key
    await state.update_data(draft=draft)
    text, markup = draft_view(store, draft)
    await cb.message.edit_text(text, reply_markup=markup)
    await cb.answer()


@router.callback_query(F.data == "doc:chscope")
async def change_scope(cb: CallbackQuery, state: FSMContext):
    draft = await _draft_or_stale(cb, state)
    if not draft:
        return
    draft["scope"] = None
    await state.update_data(draft=draft)
    await cb.message.edit_text(f"📄 «{draft['title']}»\n\n{texts.NO_SCOPE}", reply_markup=scope_keyboard())
    await cb.answer()


@router.callback_query(F.data == "doc:cancel")
async def cancel_upload(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    await cb.message.edit_text(texts.CANCELLED)
    await cb.answer()


async def commit(cb: CallbackQuery, state: FSMContext, store: Store, mode: str):
    """mode: 'save' — замінити лише якщо збіг точний; 'replace' — замінити схожі; 'separate' — не замінювати."""
    draft = await _draft_or_stale(cb, state)
    if not draft or not draft["scope"]:
        return
    plan = plan_replacement(store, draft["doc_type"], draft["scope"], draft["title"])
    do_replace = (mode == "save" and plan.mode == "auto") or (mode == "replace" and plan.docs)
    replaced = plan.docs if do_replace else []
    store.add_document(
        title=draft["title"], doc_type=draft["doc_type"], scope=draft["scope"], text=draft["text"],
        source="user", author_name=draft["author_name"], author_tg_id=cb.from_user.id,
        replace_ids=[d.id for d in replaced],
    )
    await state.clear()
    msg = texts.SAVED.format(name=draft["author_name"])
    for d in replaced:
        msg += "\n" + texts.REPLACED.format(title=d.title)
    await cb.message.edit_text(msg)
    await cb.answer()


@router.callback_query(F.data == "doc:save")
async def save_doc(cb: CallbackQuery, state: FSMContext, store: Store):
    await commit(cb, state, store, "save")


@router.callback_query(F.data == "doc:replace")
async def replace_doc(cb: CallbackQuery, state: FSMContext, store: Store):
    await commit(cb, state, store, "replace")


@router.callback_query(F.data == "doc:separate")
async def separate_doc(cb: CallbackQuery, state: FSMContext, store: Store):
    await commit(cb, state, store, "separate")


# ---------------------------------------------------------------- питання

@router.message(F.text & ~F.text.startswith("/"))
async def on_question(message: Message, bot: Bot, store: Store, groq: GroqClient, settings: Settings):
    uid = message.from_user.id
    question = " ".join(message.text.split())
    place = parse_place(question)
    general = False

    pending = PENDING_Q.pop(uid, None)
    fresh = bool(pending) and time.time() - pending[1] < PENDING_TTL and len(question.split()) <= 6
    if fresh and (place.has or GENERAL_RE.search(question.lower())):
        # відповідь на «про яке місце питаєте?» — склеюємо з початковим питанням
        general = not place.has
        question = f"{pending[0]} {question}"
        place = parse_place(question)

    await bot.send_chat_action(message.chat.id, "typing")
    found = retrieve(store, question, place, settings.max_context_docs, general=general)
    if found.status == "ask_place":
        PENDING_Q[uid] = (question, time.time())
        await message.answer(texts.ASK_PLACE)
        return
    if found.status == "none":
        await message.answer(texts.NOT_FOUND)
        return

    try:
        answer = await generate_answer(groq, question, found.docs, settings.max_doc_chars)
    except GroqError:
        log.exception("Помилка Groq")
        await message.answer(texts.LLM_ERROR)
        return
    if not answer.found:
        await message.answer(texts.NOT_FOUND)
        return

    sources = "\n".join(source_line(n, d) for n, d in answer.sources)
    hint = GENERAL_HINT if not place.has else ""
    body = answer.text[: TG_LIMIT - len(sources) - len(hint) - 20]
    await message.answer(f"{body}{hint}\n\nДжерела:\n{sources}")


@router.message()
async def on_other(message: Message):
    await message.answer(texts.UNSUPPORTED_CONTENT)