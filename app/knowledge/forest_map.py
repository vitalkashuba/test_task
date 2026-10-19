"""Карта лісу: рукавички, частини лісу та рівні конкретності порад."""
import re

FOREST = "forest"

# ключ -> (назва, частини лісу, regex для розпізнавання в тексті)
MITTENS: dict[str, tuple[str, tuple[str, ...], str]] = {
    "m_yalyna": ("Під ялиною", ("conifer",), r"\bпід\s+ялин\w*"),
    "m_sosny": ("У соснах", ("conifer",), r"\b[ув]\s+сосн\w*"),
    "m_murashnyk": ("Біля мурашника", ("conifer",), r"\b(?:біля|коло|поруч\s+з)\s+мурашник\w*|\bмурашник\w*"),
    "m_dub": ("Під дубом", ("deciduous",), r"\bпід\s+дуб\w*"),
    "m_lishchyna": ("У ліщині", ("deciduous",), r"\b[ув]\s+ліщин\w*"),
    "m_verba": ("Під вербою", ("deciduous", "river"), r"\bпід\s+верб\w*"),
    "m_hrebla": ("Біля бобрової греблі", ("river",), r"\b(?:біля|коло)\s+бобров\w*\s+гребл\w*"),
    "m_uzlissia": ("На узліссі", (), r"\bна\s+узлісс\w*|\bна\s+узлісі|\bузлісс\w*"),
}

AREAS: dict[str, tuple[str, str]] = {
    "conifer": ("хвойний ліс", r"хвойн\w*"),
    "deciduous": ("листяний ліс", r"листян\w*"),
    "river": ("біля річки", r"\b(?:біля|коло|край|над|поблизу)\s+річк\w*|\bприбереж\w*|\bберег\w*|\bна\s+берез\w*"),
}

# Документ адресований усьому лісу
FOREST_RE = re.compile(r"всіх\s+мешканців\s+лісу|всього\s+лісу|всім\s+мешканцям\s+лісу")

_MITTEN_RE = {k: re.compile(v[2]) for k, v in MITTENS.items()}
_AREA_RE = {k: re.compile(v[1]) for k, v in AREAS.items()}

ALL_SCOPES = [FOREST, *AREAS.keys(), *MITTENS.keys()]


def find_mittens(text: str) -> list[str]:
    t = text.lower()
    return [k for k, rx in _MITTEN_RE.items() if rx.search(t)]


def find_areas(text: str) -> list[str]:
    t = text.lower()
    return [k for k, rx in _AREA_RE.items() if rx.search(t)]


def areas_of(mitten: str) -> set[str]:
    return set(MITTENS[mitten][1])


def scope_level(scope: str) -> int:
    """3 — рукавичка, 2 — частина лісу, 1 — весь ліс."""
    if scope in MITTENS:
        return 3
    if scope in AREAS:
        return 2
    if scope == FOREST:
        return 1
    return 0


def scope_label(scope: str) -> str:
    if scope in MITTENS:
        return MITTENS[scope][0]
    if scope in AREAS:
        return AREAS[scope][0]
    return "весь ліс"


def scope_long(scope: str) -> str:
    if scope in MITTENS:
        return f"рукавичка «{MITTENS[scope][0]}» (найконкретніший рівень)"
    if scope in AREAS:
        return f"частина лісу: {AREAS[scope][0]}"
    return "весь ліс (загальна порада)"


DOC_TYPES: list[tuple[str, str, str]] = [
    ("fees", r"внес", "Членські внески"),
    ("duty", r"чергуван", "Чергування"),
    ("statute", r"статут|осмд", "Статут ОСМД"),
    ("rules", r"співжит", "Правила співжиття"),
    ("dangers", r"небезпек", "Небезпеки"),
    ("food", r"поживит|що\s+їсти", "Чим поживитись"),
    ("paths", r"стежк", "Стежки до сусідів"),
    ("mushrooms", r"грибн", "Грибний путівник"),
    ("insulation", r"утепл", "Утеплення"),
]
DOC_TYPE_LABELS = {k: label for k, _, label in DOC_TYPES}
