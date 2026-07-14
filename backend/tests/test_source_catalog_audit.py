from __future__ import annotations

from pathlib import Path

from app.models.epidemiology import SourceStatus
from app.services.source_catalog import OFFICIAL_SOURCE_CATALOG


def _catalog() -> dict[str, dict]:
    return {item["id"]: item for item in OFFICIAL_SOURCE_CATALOG}


def test_catalog_ids_are_unique_and_endpoints_use_https() -> None:
    ids = [item["id"] for item in OFFICIAL_SOURCE_CATALOG]
    assert len(ids) == len(set(ids))
    assert all(item["endpoint"].startswith("https://") for item in OFFICIAL_SOURCE_CATALOG)


def test_active_socrata_sources_have_verified_ids_and_matching_endpoints() -> None:
    verified = {
        "ideam-precipitation": "s54a-sgyg",
        "ideam-temperature": "sbwg-7ju4",
        "ideam-humidity": "uext-mhny",
        "ideam-stations": "hp9r-jxuu",
        "sivigila-national": "4hyg-wa9d",
        "pai-national": "6i25-2hdt",
    }
    catalog = _catalog()
    for source_id, dataset_id in verified.items():
        source = catalog[source_id]
        assert source["status"] == SourceStatus.ACTIVE.value
        assert source["source_type"] == "socrata"
        assert source["dataset_id"] == dataset_id
        assert source["endpoint"] == f"https://www.datos.gov.co/resource/{dataset_id}.json"


def test_access_model_matches_verified_public_contracts() -> None:
    catalog = _catalog()
    assert catalog["ideam-climate"]["status"] == SourceStatus.DISABLED.value
    assert (
        catalog["ideam-deforestation"]["status"]
        == SourceStatus.REQUIRES_CONFIGURATION.value
    )
    assert catalog["dane-socioeconomic"]["status"] == SourceStatus.ACTIVE.value
    for source_id in ("pai-municipal-history", "pai-municipal-2026"):
        source = catalog[source_id]
        assert source["status"] == SourceStatus.ACTIVE.value
        assert source["source_type"] == "public-file"
        assert source["endpoint"].startswith("https://www.minsalud.gov.co/")


def test_documented_audit_contains_every_verified_public_dataset() -> None:
    documentation = (
        Path(__file__).parents[1] / "docs" / "data-sources.md"
    ).read_text(encoding="utf-8")
    for dataset_id in (
        "4hyg-wa9d",
        "6i25-2hdt",
        "57sv-p2fu",
        "s54a-sgyg",
        "sbwg-7ju4",
        "uext-mhny",
        "hp9r-jxuu",
        "39dh-rc72",
        "env9-bhc9",
    ):
        assert f"`{dataset_id}`" in documentation


def test_documentation_does_not_treat_public_files_as_institutional_access() -> None:
    documentation = (
        Path(__file__).parents[1] / "docs" / "data-sources.md"
    ).read_text(encoding="utf-8")
    assert "coberturas-vacunacion-municipal-desde-1998.zip" in documentation
    assert "dosis-coberturas-biologicos-municipios-2026.zip" in documentation
    assert "Público, no" in documentation
