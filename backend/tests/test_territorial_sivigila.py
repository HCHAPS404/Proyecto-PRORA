from __future__ import annotations

from app.connectors.territorial_sivigila import (
    FEDERATION_SOURCE_ID,
    disease_from_event_and_name,
    extract_cases,
    extract_year_week,
    pad_divipola,
    profile_by_source_id,
    territorial_profiles,
)
from app.services.canonical_store import _should_replace_observation
from app.services.source_catalog import OFFICIAL_SOURCE_CATALOG


def test_federation_profiles_cover_multi_territory_and_2025() -> None:
    profiles = {item.source_id: item for item in territorial_profiles()}
    assert FEDERATION_SOURCE_ID == "sivigila-territorial-open"
    assert "sivigila-bucaramanga-dengue" in profiles
    assert profiles["sivigila-bucaramanga-dengue"].year_to == 2025
    assert profiles["sivigila-bucaramanga-events"].year_to == 2025
    assert profiles["sivigila-bucaramanga-ira"].fixed_municipality_code == "68001"
    assert profiles["sivigila-santa-rosa-cabal-events"].diseases == (
        "dengue",
        "malaria",
        "ira",
    )
    assert profiles["sivigila-boyaca-events"].kind == "aggregate"
    assert profiles["sivigila-caqueta-dengue"].kind == "case"
    catalog = {item["id"]: item for item in OFFICIAL_SOURCE_CATALOG}
    assert catalog[FEDERATION_SOURCE_ID]["configuration"]["federation"] is True
    assert len(catalog[FEDERATION_SOURCE_ID]["configuration"]["member_source_ids"]) >= 9
    for source_id in profiles:
        assert source_id in catalog
        assert catalog[source_id]["status"] == "active"


def test_pad_divipola_and_year_locale_artifacts() -> None:
    assert pad_divipola("68", "1") == "68001"
    assert pad_divipola("76", "834") == "76834"
    assert pad_divipola(None, "68001") is None
    profile = profile_by_source_id("sivigila-pereira-dengue")
    assert profile is not None
    assert extract_year_week({"ano": "2.023", "semana": "12"}, profile.fields) == (2023, 12)
    assert extract_year_week({"ano": "2.02", "semana": "12"}, profile.fields) is None
    assert extract_year_week({"ano": "2024", "semana": "53"}, profile.fields) == (2024, 53)


def test_boyaca_requires_event_name_consistency() -> None:
    # Code 210 is dengue, but Boyacá may reuse codes — name must agree.
    assert (
        disease_from_event_and_name(210, "DENGUE", allowed=("dengue", "malaria")) == "dengue"
    )
    assert disease_from_event_and_name(210, "MALARIA", allowed=("dengue", "malaria")) == "malaria"
    assert disease_from_event_and_name(210, "OTRO", allowed=("dengue",)) is None
    assert (
        disease_from_event_and_name(None, "DENGUE CON SIGNOS DE ALARMA", allowed=("dengue",))
        == "dengue"
    )


def test_case_rows_count_as_one() -> None:
    profile = profile_by_source_id("sivigila-bucaramanga-dengue")
    assert profile is not None
    assert extract_cases({"a_o": "2025", "semana": "1"}, profile) == 1
    aggregate = profile_by_source_id("sivigila-boyaca-events")
    assert aggregate is not None
    assert extract_cases({"conteo_casos": "4"}, aggregate) == 4


def test_merge_prefers_newer_year_and_keeps_territorial_over_national() -> None:
    assert _should_replace_observation(
        stored_year=2024,
        stored_source_id="sivigila-microdata-2024",
        incoming_year=2025,
        incoming_source_id="sivigila-bucaramanga-dengue",
    )
    assert not _should_replace_observation(
        stored_year=2025,
        stored_source_id="sivigila-bucaramanga-dengue",
        incoming_year=2024,
        incoming_source_id="sivigila-microdata-2024",
    )
    assert not _should_replace_observation(
        stored_year=2022,
        stored_source_id="sivigila-boyaca-events",
        incoming_year=2022,
        incoming_source_id="sivigila-national",
    )
    assert _should_replace_observation(
        stored_year=2022,
        stored_source_id="sivigila-national",
        incoming_year=2022,
        incoming_source_id="sivigila-caqueta-dengue",
    )
