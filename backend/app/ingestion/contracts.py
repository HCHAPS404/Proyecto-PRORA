"""Dependency-free canonical data contracts shared by ingestion and ML layers."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from .provenance import Provenance


@dataclass(frozen=True, slots=True)
class TerritoryRef:
    department_code: str | None = None
    municipality_code: str | None = None
    divipola_code: str | None = None
    department_name: str | None = None
    municipality_name: str | None = None


@dataclass(frozen=True, slots=True)
class EpidemiologicalObservation:
    event_code: str
    event_name: str
    epidemiological_year: int
    epidemiological_week: int
    cases: int
    territory: TerritoryRef
    provenance: Provenance
    quality_flags: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class VaccinationObservation:
    year: int
    biologic: str
    coverage_percent: float
    territory: TerritoryRef
    provenance: Provenance
    quality_flags: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ClimateObservation:
    observed_at: datetime
    station_code: str
    sensor_code: str
    metric: str
    value: float
    unit: str | None
    territory: TerritoryRef
    latitude: float | None
    longitude: float | None
    provider: str | None
    provenance: Provenance
    quality_flags: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class DeforestationObservation:
    year: int
    hectares: float
    territory: TerritoryRef
    provenance: Provenance
    quality_flags: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class SocioeconomicObservation:
    year: int
    indicator: str
    value: float
    unit: str
    territory: TerritoryRef
    provenance: Provenance
    dimensions: dict[str, Any] = field(default_factory=dict)
    quality_flags: tuple[str, ...] = ()
