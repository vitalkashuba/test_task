from app.knowledge.scope import candidate_scopes, parse_place


def scopes(q):
    return candidate_scopes(parse_place(q))


def test_verba_belongs_to_deciduous_and_river():
    assert scopes("Які внески в рукавичці Під вербою?") == {"forest", "m_verba", "deciduous", "river"}


def test_uzlissia_belongs_to_no_area():
    assert scopes("Чергування на узліссі") == {"forest", "m_uzlissia"}


def test_conifer_mitten():
    assert scopes("Небезпеки у соснах") == {"forest", "m_sosny", "conifer"}


def test_explicit_area():
    assert scopes("Що їсти в листяному лісі?") == {"forest", "deciduous"}


def test_beaver_dam_is_river():
    assert scopes("Внески біля бобрової греблі") == {"forest", "m_hrebla", "river"}


def test_no_place():
    assert not parse_place("Що робити при пожежі?").has
