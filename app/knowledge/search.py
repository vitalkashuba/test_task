"""Добір документів для відповіді з урахуванням місця і рівня конкретності."""
import re
from dataclasses import dataclass, field

from .forest_map import FOREST, scope_level
from .scope import Place, candidate_scopes
from .store import Doc, Store

STOP_WORDS = {
    "коли", "який", "яка", "яке", "які", "яких", "чому", "скільки", "треба", "потрібно",
    "можна", "мене", "мені", "нашої", "нашій", "нашого", "цього", "також", "тому", "бути",
    "чого", "куди", "будь", "дякую", "привіт", "якщо", "щоб", "чим", "між",
}
STOP_PREFIXES = (
    "рукав", "звір", "розкаж", "скаж", "підкаж", "ласк", "дякув", "порад",
    "хвойн", "листян", "річк", "бобров", "узлісс", "ялин", "сосн", "мурашн",
    "дубом", "ліщин", "верб", "гребл",
)

# Підказки: про який тип документа питають
TYPE_HINTS: list[tuple[str, str]] = [
    (r"внес|плат[иі]|скарбн|складчин", "fees"),
    (r"черг[аиу]|чергов|вартув", "duty"),
    (r"статут|осмд|збор[иі]|голосув", "statute"),
    (r"правил\w*\s+співжит|співжит|шум|тиш[аі]", "rules"),
    (r"небезпек|небезпечн|загроз|щук|обережн", "dangers"),
    (r"\bїсти\b|\bїж|харч|поживит|\bкорм|голодн", "food"),
    (r"стежк|сусід", "paths"),
    (r"гриб", "mushrooms"),
    (r"утепл|утепли|холод|зиму", "insulation"),
]


@dataclass
class Retrieval:
    status: str  # 'ok' | 'ask_place' | 'none'
    docs: list[Doc] = field(default_factory=list)


def query_terms(question: str, max_terms: int = 8) -> list[str]:
    words = re.findall(r"[а-яіїєґ'’]{4,}", question.lower())
    terms: list[str] = []
    for w in words:
        if w in STOP_WORDS or w.startswith(STOP_PREFIXES):
            continue
        stem = w[:4]
        if stem not in terms:
            terms.append(stem)
    return terms[:max_terms]


def hinted_types(question: str) -> set[str]:
    q = question.lower()
    return {t for pattern, t in TYPE_HINTS if re.search(pattern, q)}


def _unique(docs: list[Doc]) -> list[Doc]:
    seen, out = set(), []
    for d in docs:
        if d.id not in seen:
            seen.add(d.id)
            out.append(d)
    return out


def retrieve(store: Store, question: str, place: Place, limit: int = 8) -> Retrieval:
    terms = query_terms(question)
    hints = hinted_types(question)
    if place.has and re.search(r"правил", question.lower()):
        hints.add("rules")  # «які правила у рукавичці У соснах» → правила співжиття

    if place.has:
        scopes = candidate_scopes(place)
        in_scope = store.active_in_scopes(scopes)
        hinted = sorted(
            (d for d in in_scope if d.doc_type in hints), key=lambda d: -scope_level(d.scope)
        )
        ranked = store.search(terms, scopes, limit=16)
        # Якщо питають про конкретний тип документа, сторонні збіги додаємо обережно (лише 2),
        # щоб відповідь не перетворювалась на переказ усього підряд.
        merged = _unique(hinted + (ranked[:2] if hinted else ranked))
        if not merged:
            merged = sorted(in_scope, key=lambda d: -scope_level(d.scope))
        return Retrieval("ok", merged[:limit]) if merged else Retrieval("none")

    # Місце не названо
    if hints and any(d.doc_type in hints and d.scope != FOREST for d in store.all_active()):
        return Retrieval("ask_place")
    hits = store.search(terms, None, limit=24)
    forest_hits = [d for d in hits if d.scope == FOREST]
    if forest_hits:
        return Retrieval("ok", forest_hits[:limit])
    if hits:
        return Retrieval("ask_place")
    return Retrieval("none")
