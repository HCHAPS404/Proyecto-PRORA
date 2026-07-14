from __future__ import annotations

import asyncio
from datetime import date

from fastapi.testclient import TestClient

from app.models.epidemiology import (
    DataSource,
    EpidemiologicalObservation,
    Municipality,
    SourceStatus,
)


def test_historical_territories_are_available_without_forecasts(client: TestClient) -> None:
    async def seed() -> None:
        factory = client.app.state.session_factory
        async with factory() as session:
            session.add(
                DataSource(
                    id="sivigila-history",
                    name="SIVIGILA historico",
                    institution="INS",
                    source_type="socrata",
                    status=SourceStatus.ACTIVE.value,
                )
            )
            session.add_all(
                [
                    Municipality(
                        code="76001",
                        name="Cali",
                        department_code="76",
                        department_name="Valle del Cauca",
                        population=2_280_000,
                        latitude=3.4516,
                        longitude=-76.532,
                    ),
                    Municipality(
                        code="76520",
                        name="Palmira",
                        department_code="76",
                        department_name="Valle del Cauca",
                        population=350_000,
                    ),
                    Municipality(
                        code="50001",
                        name="Villavicencio",
                        department_code="50",
                        department_name="Meta",
                        population=550_000,
                    ),
                ]
            )
            await session.flush()
            session.add_all(
                [
                    EpidemiologicalObservation(
                        municipality_code="76001",
                        disease="dengue",
                        week_start=date(2022, 1, 2),
                        epidemiological_week=1,
                        epidemiological_year=2022,
                        cases=5,
                        is_preliminary=False,
                        quality_score=0.96,
                        source_id="sivigila-history",
                    ),
                    EpidemiologicalObservation(
                        municipality_code="76001",
                        disease="dengue",
                        week_start=date(2022, 1, 16),
                        epidemiological_week=3,
                        epidemiological_year=2022,
                        cases=12,
                        is_preliminary=True,
                        quality_score=0.87,
                        source_id="sivigila-history",
                    ),
                    EpidemiologicalObservation(
                        municipality_code="76520",
                        disease="dengue",
                        week_start=date(2022, 1, 9),
                        epidemiological_week=2,
                        epidemiological_year=2022,
                        cases=4,
                        is_preliminary=False,
                        quality_score=0.94,
                        source_id="sivigila-history",
                    ),
                    EpidemiologicalObservation(
                        municipality_code="50001",
                        disease="malaria",
                        week_start=date(2022, 1, 23),
                        epidemiological_week=4,
                        epidemiological_year=2022,
                        cases=3,
                        is_preliminary=False,
                        quality_score=0.91,
                        source_id="sivigila-history",
                    ),
                ]
            )
            await session.commit()

    asyncio.run(seed())

    response = client.get("/api/v1/analytics/historical-territories?disease=dengue")
    assert response.status_code == 200
    body = response.json()
    assert body["disease"] == "dengue"
    assert body["total"] == 2
    assert body["metadata"]["status"] == "ok"
    assert body["metadata"]["data_kind"] == "historical_observations"
    assert body["metadata"]["risk_included"] is False
    assert body["metadata"]["forecast_eligibility_required"] is False

    cali = body["items"][0]
    assert cali["cod_dane"] == "76001"
    assert cali["latest_week"] == "2022-01-16"
    assert cali["observation_rows"] == 2
    assert cali["total_observed_cases"] == 17
    assert cali["latest_observed_cases"] == 12
    assert cali["latest_is_preliminary"] is True
    assert cali["latest_quality_score"] == 0.87
    assert cali["latitude"] == 3.4516
    assert cali["longitude"] == -76.532
    assert "risk_score" not in cali
    assert "risk_level" not in cali

    palmira = body["items"][1]
    assert palmira["cod_dane"] == "76520"
    assert palmira["latest_week"] == "2022-01-09"
    assert palmira["latest_observed_cases"] == 4

    history = client.get(
        "/api/v1/risk/municipalities/76001/history?disease=dengue"
    )
    assert history.status_code == 200
    assert [point["observed"] for point in history.json()] == [5, 12]


def test_historical_territories_support_filters_and_empty_state(client: TestClient) -> None:
    async def seed() -> None:
        factory = client.app.state.session_factory
        async with factory() as session:
            session.add(
                DataSource(
                    id="sivigila-history",
                    name="SIVIGILA historico",
                    institution="INS",
                    source_type="socrata",
                    status=SourceStatus.ACTIVE.value,
                )
            )
            session.add_all(
                [
                    Municipality(
                        code="76001",
                        name="Cali",
                        department_code="76",
                        department_name="Valle del Cauca",
                    ),
                    Municipality(
                        code="50001",
                        name="Villavicencio",
                        department_code="50",
                        department_name="Meta",
                    ),
                ]
            )
            await session.flush()
            session.add_all(
                [
                    EpidemiologicalObservation(
                        municipality_code="76001",
                        disease="dengue",
                        week_start=date(2022, 1, 2),
                        epidemiological_week=1,
                        epidemiological_year=2022,
                        cases=5,
                        source_id="sivigila-history",
                    ),
                    EpidemiologicalObservation(
                        municipality_code="50001",
                        disease="dengue",
                        week_start=date(2022, 1, 2),
                        epidemiological_week=1,
                        epidemiological_year=2022,
                        cases=3,
                        source_id="sivigila-history",
                    ),
                ]
            )
            await session.commit()

    asyncio.run(seed())

    by_department = client.get(
        "/api/v1/analytics/historical-territories?disease=dengue&department=76"
    )
    assert by_department.status_code == 200
    assert [item["cod_dane"] for item in by_department.json()["items"]] == ["76001"]

    by_search = client.get(
        "/api/v1/analytics/historical-territories?disease=dengue&search=villavi"
    )
    assert by_search.status_code == 200
    assert [item["cod_dane"] for item in by_search.json()["items"]] == ["50001"]

    empty = client.get("/api/v1/analytics/historical-territories?disease=zika")
    assert empty.status_code == 200
    assert empty.json()["items"] == []
    assert empty.json()["metadata"]["status"] == "no_data"

    invalid_department = client.get(
        "/api/v1/analytics/historical-territories?disease=dengue&department=7"
    )
    assert invalid_department.status_code == 422
