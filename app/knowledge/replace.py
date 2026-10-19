"""Заміна застарілих порад: «новіший варіант того самого документа для того самого місця»."""
from dataclasses import dataclass, field
from difflib import SequenceMatcher

from .classify import title_key
from .store import Doc, Store


@dataclass
class Plan:
    mode: str  # 'auto' — той самий тип і місце; 'ask' — схожа назва, питаємо; 'none'
    docs: list[Doc] = field(default_factory=list)


def plan_replacement(store: Store, doc_type: str, scope: str | None, title: str) -> Plan:
    if not scope:
        return Plan("none")
    same_scope = store.active_in_scopes([scope])
    exact = [d for d in same_scope if d.doc_type == doc_type]
    if exact:
        return Plan("auto", exact)
    key = title_key(title)
    similar = [
        d for d in same_scope
        if SequenceMatcher(None, title_key(d.title), key).ratio() >= 0.6
    ]
    if similar:
        return Plan("ask", similar)
    return Plan("none")
