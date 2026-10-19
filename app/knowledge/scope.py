"""Розпізнавання місця (рукавичка / частина лісу) в питанні звіра."""
from dataclasses import dataclass, field

from .forest_map import FOREST, areas_of, find_areas, find_mittens


@dataclass
class Place:
    mittens: list[str] = field(default_factory=list)
    areas: set[str] = field(default_factory=set)  # явно названі частини лісу

    @property
    def has(self) -> bool:
        return bool(self.mittens or self.areas)


def parse_place(question: str) -> Place:
    return Place(mittens=find_mittens(question), areas=set(find_areas(question)))


def candidate_scopes(place: Place) -> set[str]:
    """Усі рівні, поради яких стосуються названого місця."""
    scopes = {FOREST} | set(place.mittens) | set(place.areas)
    for m in place.mittens:
        scopes |= areas_of(m)
    return scopes
