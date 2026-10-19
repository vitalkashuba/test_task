import pytest

from app.knowledge.replace import plan_replacement
from app.knowledge.scope import parse_place
from app.knowledge.search import retrieve
from app.knowledge.store import Store


@pytest.fixture
def store():
    s = Store(":memory:")
    add = lambda **kw: s.add_document(source=kw.pop("source", "archive"), **kw)
    add(title="Членські внески рукавички Під дубом", doc_type="fees", scope="m_dub",
        text="Внесок — 4 жолуді з дорослого звіра на місяць. Здавати до 10 числа.")
    add(title="Членські внески рукавички У соснах", doc_type="fees", scope="m_sosny",
        text="Розмір внеску: 2 соснові шишки щотижня.")
    add(title="Небезпеки листяного лісу", doc_type="dangers", scope="deciduous",
        text="Кабани риють землю. Остерігайтеся ям.")
    add(title="Небезпеки біля річки", doc_type="dangers", scope="river",
        text="Щука живе в глибоких заводях.")
    add(title="Що робити при пожежі", doc_type="other:що робити при пожежі", scope="forest",
        text="Довгий безперервний крик означає пожежу. Біжіть до річки проти вітру.")
    return s


def test_fts_matches_inflections(store):
    # «внески» у питанні має знайти «внесок/внеску» у тексті
    assert store.search(["внес"], {"m_dub"})


def test_place_question_finds_own_mitten_only(store):
    r = retrieve(store, "Які внески в рукавичці Під дубом?", parse_place("Під дубом"))
    titles = [d.title for d in r.docs]
    assert titles[0] == "Членські внески рукавички Під дубом"
    assert all("соснах" not in t for t in titles)


def test_specific_level_comes_first_for_verba(store):
    q = "Які небезпеки під вербою?"
    r = retrieve(store, q, parse_place(q))
    scopes = [d.scope for d in r.docs]
    assert set(scopes) >= {"deciduous", "river"}


def test_no_place_asks_for_place_when_docs_are_per_mitten(store):
    q = "Які внески треба платити?"
    assert retrieve(store, q, parse_place(q)).status == "ask_place"


def test_general_question_answered_without_place(store):
    q = "Що робити при пожежі?"
    r = retrieve(store, q, parse_place(q))
    assert r.status == "ok" and r.docs[0].scope == "forest"


def test_replacement_auto_for_same_type_and_scope(store):
    plan = plan_replacement(store, "fees", "m_dub", "Нові внески Під дубом")
    assert plan.mode == "auto" and len(plan.docs) == 1


def test_replacement_deactivates_old_version(store):
    plan = plan_replacement(store, "fees", "m_dub", "Внески Під дубом 2026")
    new_id = store.add_document(
        title="Внески Під дубом 2026", doc_type="fees", scope="m_dub", source="user",
        author_name="Скарбник", author_tg_id=1, text="Тепер 5 жолудів на місяць.",
        replace_ids=[d.id for d in plan.docs],
    )
    active = [d for d in store.active_in_scopes(["m_dub"]) if d.doc_type == "fees"]
    assert [d.id for d in active] == [new_id]
    q = "Які внески під дубом?"
    texts = " ".join(d.text for d in retrieve(store, q, parse_place(q)).docs)
    assert "5 жолудів" in texts and "4 жолуді" not in texts


def test_replacement_ask_for_similar_title(store):
    store.add_document(title="Правила толоки", doc_type="other:правила толоки", scope="forest",
                       source="archive", text="Толока в першу суботу жовтня.")
    plan = plan_replacement(store, "other:правила толоки 2026", "forest", "Правила толоки 2026")
    assert plan.mode == "ask"


def test_only_author_can_delete(store):
    doc_id = store.add_document(title="X", doc_type="other:x", scope="forest", source="user",
                                author_name="А", author_tg_id=7, text="текст")
    assert not store.deactivate(doc_id, 8)
    assert store.deactivate(doc_id, 7)


def test_user_name_asked_once(store):
    assert store.get_user_name(5) is None
    store.set_user_name(5, "Ведмідь")
    assert store.get_user_name(5) == "Ведмідь"
