"""Canonical DIVIPOLA formatting and lookup helpers."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from .contracts import TerritoryRef


def digits(value: Any, width: int) -> str | None:
    if value is None or value == "":
        return None
    raw = str(value).split(".", 1)[0]
    only_digits = "".join(character for character in raw if character.isdigit())
    return only_digits.zfill(width) if only_digits else None


def territory(
    *,
    department_code: Any = None,
    municipality_code: Any = None,
    department_name: str | None = None,
    municipality_name: str | None = None,
) -> TerritoryRef:
    department = digits(department_code, 2)
    municipality_raw = digits(municipality_code, 3 if department else 5)
    if municipality_raw and len(municipality_raw) == 5:
        department = department or municipality_raw[:2]
        municipality = municipality_raw[2:]
        combined = municipality_raw
    else:
        municipality = municipality_raw
        combined = f"{department}{municipality}" if department and municipality else None
    return TerritoryRef(
        department_code=department,
        municipality_code=municipality,
        divipola_code=combined,
        department_name=department_name,
        municipality_name=municipality_name,
    )


def normalize_name(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value)
    ascii_value = "".join(
        character for character in decomposed if not unicodedata.combining(character)
    )
    return re.sub(r"\s+", " ", ascii_value.strip().upper())


@dataclass(slots=True)
class DIVIPOLAIndex:
    by_code: dict[str, TerritoryRef]
    by_name: dict[tuple[str, str], TerritoryRef]

    @classmethod
    def from_arcgis(cls, rows: Iterable[dict[str, Any]]) -> DIVIPOLAIndex:
        by_code: dict[str, TerritoryRef] = {}
        by_name: dict[tuple[str, str], TerritoryRef] = {}
        for row in rows:
            item = territory(
                department_code=row.get("DPTO_CCDGO"),
                municipality_code=row.get("MPIO_CCDGO"),
                department_name=row.get("DPTO_CNMBRE"),
                municipality_name=row.get("MPIO_CNMBRE"),
            )
            if item.divipola_code:
                by_code[item.divipola_code] = item
            if item.department_name and item.municipality_name:
                key = (
                    normalize_name(item.department_name),
                    normalize_name(item.municipality_name),
                )
                by_name[key] = item
        return cls(by_code=by_code, by_name=by_name)

    def resolve(self, item: TerritoryRef) -> TerritoryRef | None:
        if item.divipola_code and item.divipola_code in self.by_code:
            return self.by_code[item.divipola_code]
        if item.department_name and item.municipality_name:
            key = (
                normalize_name(item.department_name),
                normalize_name(item.municipality_name),
            )
            return self.by_name.get(key)
        return None
