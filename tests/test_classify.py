from pathlib import Path

import pytest

from app.knowledge.classify import classify, detect_doc_type, detect_scope
from app.knowledge.forest_map import MITTENS

ARCHIVE = Path(__file__).parent.parent / "data" / "archive"


@pytest.mark.parametrize("name,dtype,scope", [
    ("Членські внески рукавички Під дубом.txt", "fees", "m_dub"),
    ("Чергування в рукавичці У соснах.pdf", "duty", "m_sosny"),
    ("Статут ОСМД На узліссі.pdf", "statute", "m_uzlissia"),
    ("Небезпеки поруч із рукавичкою Біля бобрової греблі.pdf", "dangers", "m_hrebla"),
    ("Чим поживитись поруч із рукавичкою У ліщині.docx", "food", "m_lishchyna"),
    ("Небезпеки хвойного лісу.txt", "dangers", "conifer"),
    ("Що їсти біля річки.txt", "food", "river"),
    ("Як утеплити рукавичку в листяному лісі.docx", "insulation", "deciduous"),
])
def test_filename_classification(name, dtype, scope):
    _, t, s = classify(name, "")
    assert (t, s) == (dtype, scope)


def test_scope_from_header_not_title():
    # у назві немає місця, але шапка вказує адресата
    assert detect_scope("Броди і коли бобри відкривають греблю", "Ця пам'ятка для мешканців біля річки.") == "river"
    assert detect_scope("Коли падають жолуді й горіхи", "Для мешканців листяного лісу.") == "deciduous"
    assert detect_scope("Як не заблукати серед однакових сосен", "Ця порада для мешканців хвойного лісу.") == "conifer"
    assert detect_scope("Календар сезонів", "Цей календар для всіх мешканців лісу.") == "forest"


def test_unknown_scope_is_none():
    assert detect_scope("Нова порада", "Просто текст без адресата.") is None


def test_other_type_uses_title():
    assert detect_doc_type("Правила толоки").startswith("other:")


def test_whole_archive_resolves():
    """Кожен із 78 файлів архіву має отримати тип і місце без питань до автора."""
    from app.ingest.parsers import parse_docx, parse_pdf, parse_txt

    unresolved = []
    for p in sorted(ARCHIVE.iterdir()):
        if p.suffix == ".pdf":
            pages, scans = parse_pdf(p.read_bytes())
            text = "" if scans else "\n".join(pages)
        elif p.suffix == ".docx":
            text = parse_docx(p.read_bytes())
        else:
            text = parse_txt(p.read_bytes())
        _, _, scope = classify(p.name, text)
        if scope is None:
            unresolved.append(p.name)
    assert not unresolved, unresolved


def test_all_mittens_defined():
    assert len(MITTENS) == 8
