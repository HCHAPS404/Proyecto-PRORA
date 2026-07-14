from __future__ import annotations

import asyncio
from datetime import date, timedelta

from fastapi.testclient import TestClient

from app.models.epidemiology import (
    AlertEvent,
    EpidemiologicalObservation,
    Forecast,
    ModelVersion,
    Municipality,
)


def test_disease_coverage_reports_all_priorities_without_inventing_availability(
    client: TestClient,
) -> None:
    response = client.get("/api/v1/sources/disease-coverage")
    assert response.status_code == 200
    items = response.json()
    assert [item["disease"] for item in items] == [
        "dengue",
        "malaria",
        "chikunguna",
        "zika",
        "leishmaniasis",
        "ira",
    ]
    assert all(item["observation_status"] == "no_data" for item in items)
    assert all(item["operational_ready"] is False for item in items)
    assert all("no_observations" in item["blocking_reasons"] for item in items)


def test_disease_coverage_separates_historical_and_operational_output(
    client: TestClient,
) -> None:
    latest_sunday = date.today() - timedelta(days=(date.today().weekday() + 1) % 7)

    async def seed() -> None:
        factory = client.app.state.session_factory
        async with factory() as session:
            session.add_all(
                [
                    Municipality(
                        code="76001",
                        name="Cali",
                        department_code="76",
                        department_name="Valle del Cauca",
                    ),
                    Municipality(
                        code="27001",
                        name="Quibdo",
                        department_code="27",
                        department_name="Choco",
                    ),
                ]
            )
            await session.flush()
            session.add_all(
                [
                    EpidemiologicalObservation(
                        municipality_code="76001",
                        disease="dengue",
                        week_start=date(2022, 12, 25),
                        epidemiological_week=52,
                        epidemiological_year=2022,
                        cases=12,
                        source_id="sivigila-national",
                    ),
                    EpidemiologicalObservation(
                        municipality_code="27001",
                        disease="malaria",
                        week_start=latest_sunday,
                        epidemiological_week=latest_sunday.isocalendar().week,
                        epidemiological_year=latest_sunday.year,
                        cases=8,
                        source_id="sivigila-current-authorized",
                    ),
                ]
            )
            dengue_model = ModelVersion(
                disease="dengue",
                horizon_weeks=4,
                version="dengue-test",
                stage="champion",
                artifact_uri="models/dengue-test",
            )
            malaria_model = ModelVersion(
                disease="malaria",
                horizon_weeks=4,
                version="malaria-test",
                stage="champion",
                artifact_uri="models/malaria-test",
            )
            session.add_all([dengue_model, malaria_model])
            await session.flush()
            dengue_forecast = Forecast(
                municipality_code="76001",
                disease="dengue",
                target_week=date(2023, 1, 22),
                horizon_weeks=4,
                predicted_cases=14,
                interval_lower=9,
                interval_upper=21,
                outbreak_probability=0.72,
                risk_level="high",
                observation_cutoff=date(2022, 12, 25),
                observation_age_days=(date.today() - date(2022, 12, 25)).days,
                operationally_eligible=False,
                model_version_id=dengue_model.id,
            )
            malaria_forecast = Forecast(
                municipality_code="27001",
                disease="malaria",
                target_week=latest_sunday + timedelta(weeks=4),
                horizon_weeks=4,
                predicted_cases=11,
                interval_lower=6,
                interval_upper=17,
                outbreak_probability=0.81,
                risk_level="critical",
                observation_cutoff=latest_sunday,
                observation_age_days=(date.today() - latest_sunday).days,
                operationally_eligible=True,
                model_version_id=malaria_model.id,
            )
            session.add_all([dengue_forecast, malaria_forecast])
            await session.flush()
            session.add(
                AlertEvent(
                    forecast_id=malaria_forecast.id,
                    threshold=0.75,
                    status="open",
                )
            )
            await session.commit()

    asyncio.run(seed())
    response = client.get("/api/v1/sources/disease-coverage")
    assert response.status_code == 200
    by_disease = {item["disease"]: item for item in response.json()}

    dengue = by_disease["dengue"]
    assert dengue["observation_status"] == "historical"
    assert dengue["source_ids"] == ["sivigila-national"]
    assert dengue["champion_model_horizons"] == [4]
    assert dengue["historical_forecasts"] == 1
    assert dengue["operational_forecasts"] == 0
    assert dengue["operational_ready"] is False
    assert "epidemiological_cutoff_is_historical" in dengue["blocking_reasons"]

    malaria = by_disease["malaria"]
    assert malaria["observation_status"] == "current"
    assert malaria["source_ids"] == ["sivigila-current-authorized"]
    assert malaria["operational_forecasts"] == 1
    assert malaria["open_operational_alerts"] == 1
    assert malaria["operational_ready"] is True
    assert malaria["blocking_reasons"] == []

    alerts = client.get("/api/v1/risk/alerts?disease=malaria")
    assert alerts.status_code == 200
    assert len(alerts.json()) == 1
    assert alerts.json()[0]["operationally_eligible"] is True
    assert alerts.json()[0]["target_week"] == str(latest_sunday + timedelta(weeks=4))
    assert alerts.json()[0]["issued_at"]
