from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from itertools import combinations

from kobold.store import TsvStore

LIFESPAN = re.compile(r",\s*\d{4}\s*-\s*\d{0,4}$")
DOTS = re.compile(r"\.")


def alias_key(name: str) -> str:
    return name.strip(" .")


class AuthorStore(TsvStore):
    fields = ("alias", "canonical")

    def to_fields(self, key: str, entry: str) -> dict:
        return {"alias": key, "canonical": entry}

    def from_fields(self, record: dict) -> tuple[str, str]:
        return record["alias"], record["canonical"]

    @property
    def aliases(self) -> dict[str, str]:
        return self.entries

    def forget(self, aliases: Iterable[str]) -> None:
        for alias in aliases:
            self.entries.pop(alias_key(alias), None)

    def learn(self, merged: Mapping[str, str]) -> None:
        for alias, canonical in merged.items():
            final = merged.get(canonical, canonical)
            self.entries[alias_key(alias)] = alias_key(final)
            for known, target in self.entries.items():
                if alias_key(target) == alias_key(alias):
                    self.entries[known] = alias_key(final)


def split_name(folder: str) -> tuple[str, list[str]]:
    surname, _, given = LIFESPAN.sub("", folder).partition(", ")
    return surname.casefold(), [DOTS.sub("", g).casefold() for g in given.split()]


def extends(shorter: list[str], longer: list[str]) -> bool:
    return (
        bool(shorter) and len(shorter) <= len(longer) and all(a == b or (len(a) == 1 and b.startswith(a)) for a, b in zip(shorter, longer))
    )


def same_person(one: str, other: str) -> bool:
    surname, given = split_name(one)
    other_surname, other_given = split_name(other)
    if LIFESPAN.search(one) or LIFESPAN.search(other):
        return (surname, given) == (other_surname, other_given)
    return surname == other_surname and (extends(given, other_given) or extends(other_given, given))


def swapped(folder: str) -> str:
    surname, _, given = folder.partition(", ")
    return f"{given}, {surname}"


def fullness(name: str, counts: Mapping[str, int]) -> tuple:
    given = split_name(name)[1]
    return len(given), sum(map(len, given)), counts[name]


def canonical_of(one: str, other: str, counts: Mapping[str, int]) -> str:
    if LIFESPAN.search(one) or LIFESPAN.search(other):
        return min((one, other), key=len)
    return max((one, other), key=lambda name: fullness(name, counts))


def inversion_winner(one: str, other: str, counts: Mapping[str, int]) -> str:
    return "" if counts[one] == counts[other] else max((one, other), key=counts.__getitem__)


def pair_canonical(one: str, other: str, counts: Mapping[str, int]) -> str:
    if other == swapped(one):
        return inversion_winner(one, other, counts)
    return canonical_of(one, other, counts) if same_person(one, other) else ""


def obvious_groups(counts: Mapping[str, int]) -> list[dict]:
    chosen: dict[str, str] = {}
    for one, other in combinations(sorted(counts), 2):
        if canonical := pair_canonical(one, other, counts):
            alias = other if canonical == one else one
            chosen.setdefault(alias, canonical)
    groups: dict[str, list[str]] = {}
    for alias, canonical in chosen.items():
        groups.setdefault(canonical, []).append(alias)
    return [{"canonical": canonical, "aliases": sorted(aliases)} for canonical, aliases in sorted(groups.items())]
