"""Canonicalization, quality and provenance for external data ingestion."""

from .contracts import (
    ClimateObservation,
    DeforestationObservation,
    EpidemiologicalObservation,
    SocioeconomicObservation,
    TerritoryRef,
    VaccinationObservation,
)
from .pipeline import IngestionEnvelope, normalize_page

__all__ = [
    "ClimateObservation",
    "DeforestationObservation",
    "EpidemiologicalObservation",
    "IngestionEnvelope",
    "SocioeconomicObservation",
    "TerritoryRef",
    "VaccinationObservation",
    "normalize_page",
]
