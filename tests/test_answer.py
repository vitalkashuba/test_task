from app.knowledge.store import Doc
from app.llm.answer import cited_numbers, parse_llm_json, source_line


def mk(source="user"):
    return Doc(1, "Внески Під дубом", "fees", "m_dub", "Кабан", 1, source, "т", "2026-10-14T09:00:00+00:00", 1)


def test_sources_show_author_and_date():
    line = source_line(1, mk())
    assert "Кабан" in line and "14.10.2026" in line and "Під дубом" in line


def test_archive_source_has_unknown_author():
    assert "автор невідомий" in source_line(2, mk("archive"))


def test_cited_numbers_ignores_out_of_range():
    assert cited_numbers("Так [2]. Ще [1][2] і [9]", 3) == [2, 1]


def test_parse_llm_json_tolerates_wrapping():
    assert parse_llm_json('Ось: {"found": true, "answer": "ок [1]"}')["found"] is True
    assert parse_llm_json("не json")["found"] is False
