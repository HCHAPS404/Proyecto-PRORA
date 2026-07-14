from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.models.entities import AlertRule, NotificationDelivery
from app.models.epidemiology import (
    AlertEvent,
    DataSource,
    EpidemiologicalBulletinAggregate,
    EpidemiologicalObservation,
    Forecast,
    IngestionRun,
    ModelVersion,
    Municipality,
)
from app.services.alert_delivery import evaluate_alert_rules


def test_alert_rules_reject_non_canonical_diseases_and_horizons(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    base = {
        "name": "Regla no operable",
        "territories": [],
        "risk_threshold": 0.7,
        "channels": ["in_app"],
    }
    unknown = client.post(
        "/api/v1/alerts",
        headers=auth_headers,
        json={**base, "disease": "covid", "horizon_weeks": 4},
    )
    assert unknown.status_code == 422

    invalid_horizon = client.post(
        "/api/v1/alerts",
        headers=auth_headers,
        json={**base, "disease": "dengue", "horizon_weeks": 12},
    )
    assert invalid_horizon.status_code == 422


def test_alert_evaluation_pages_all_current_signals_and_archives_expired(
    client: TestClient, registered: dict
) -> None:
    today = date.today()
    municipalities = (
        ("05001", "Medellin", "05", "Antioquia", 1),
        ("05002", "Abejorral", "05", "Antioquia", 3),
        ("76001", "Cali", "76", "Valle del Cauca", 2),
        ("76002", "Alcala", "76", "Valle del Cauca", 4),
        ("11001", "Bogota", "11", "Bogota D.C.", 5),
    )

    async def seed_and_evaluate() -> tuple[str, int, int, int, int]:
        async with client.app.state.session_factory() as session:
            session.add_all(
                [
                    Municipality(
                        code=code,
                        name=name,
                        department_code=department_code,
                        department_name=department_name,
                    )
                    for code, name, department_code, department_name, _ in municipalities
                ]
                + [
                    Municipality(
                        code="08001",
                        name="Barranquilla",
                        department_code="08",
                        department_name="Atlantico",
                    )
                ]
            )
            model = ModelVersion(
                disease="dengue",
                horizon_weeks=4,
                version="hardening-h4",
                stage="champion",
                artifact_uri="models/hardening-h4",
            )
            session.add(model)
            await session.flush()
            for code, _, _, _, weeks in municipalities:
                forecast = Forecast(
                    municipality_code=code,
                    disease="dengue",
                    issued_at=datetime.now(UTC),
                    target_week=today + timedelta(weeks=weeks),
                    horizon_weeks=4,
                    predicted_cases=20 + weeks,
                    interval_lower=10,
                    interval_upper=30,
                    outbreak_probability=0.9,
                    risk_level="critical",
                    operationally_eligible=True,
                    model_version_id=model.id,
                )
                session.add(forecast)
                await session.flush()
                session.add(AlertEvent(forecast_id=forecast.id, threshold=0.8, status="open"))
            expired_forecast = Forecast(
                municipality_code="08001",
                disease="dengue",
                issued_at=datetime.now(UTC) - timedelta(weeks=5),
                target_week=today - timedelta(days=1),
                horizon_weeks=4,
                predicted_cases=99,
                interval_lower=80,
                interval_upper=120,
                outbreak_probability=0.99,
                risk_level="critical",
                operationally_eligible=True,
                model_version_id=model.id,
            )
            session.add(expired_forecast)
            await session.flush()
            expired_alert = AlertEvent(
                forecast_id=expired_forecast.id,
                threshold=0.8,
                status="open",
            )
            session.add(expired_alert)
            rule = AlertRule(
                user_id=registered["user"]["id"],
                name="Dengue nacional",
                disease="dengue",
                territories=[],
                risk_threshold=0.7,
                horizon_weeks=4,
                channels=["in_app"],
                enabled=True,
            )
            session.add(rule)
            await session.flush()
            result = await evaluate_alert_rules(session, limit=2)
            await session.commit()
            repeated = await evaluate_alert_rules(session, limit=2)
            await session.commit()
            await session.refresh(expired_alert)
            delivery_count = int(
                await session.scalar(select(func.count(NotificationDelivery.id))) or 0
            )
            return (
                expired_alert.status,
                result.alerts_evaluated,
                result.deliveries_created,
                repeated.deliveries_created,
                delivery_count,
            )

    assert asyncio.run(seed_and_evaluate()) == ("archived", 5, 5, 0, 5)

    risk_map = client.get("/api/v1/risk/map?disease=dengue&horizon=4")
    assert risk_map.status_code == 200
    assert {item["cod_dane"] for item in risk_map.json()} == {
        "05001",
        "05002",
        "76001",
        "76002",
        "11001",
    }

    filtered = client.get(
        "/api/v1/risk/alerts",
        params={
            "territory": "05",
            "horizon": 4,
            "from": str(today + timedelta(weeks=2)),
            "to": str(today + timedelta(weeks=4)),
        },
    )
    assert filtered.status_code == 200
    assert [item["cod_dane"] for item in filtered.json()] == ["05002"]
    assert filtered.headers["x-total-count"] == "1"

    department = client.get("/api/v1/risk/alerts?department=76&horizon=4")
    assert [item["cod_dane"] for item in department.json()] == ["76002", "76001"]
    archived = client.get("/api/v1/risk/alerts?status=archived&cod_dane=08001")
    assert archived.status_code == 200
    assert archived.json()[0]["status"] == "archived"
    assert archived.json()[0]["operationally_eligible"] is False


def test_summary_marks_sparse_comparisons_as_non_comparable(client: TestClient) -> None:
    async def seed() -> None:
        async with client.app.state.session_factory() as session:
            session.add_all(
                [
                    Municipality(
                        code="99001",
                        name="Sparse",
                        department_code="99",
                        department_name="Pruebas",
                    ),
                    Municipality(
                        code="99002",
                        name="Window",
                        department_code="99",
                        department_name="Pruebas",
                    ),
                ]
            )
            await session.flush()
            for week, cases in ((date(2024, 1, 7), 5), (date(2024, 3, 3), 10)):
                session.add(
                    EpidemiologicalObservation(
                        municipality_code="99001",
                        disease="dengue",
                        week_start=week,
                        epidemiological_week=week.isocalendar().week,
                        epidemiological_year=week.year,
                        cases=cases,
                        source_id="sivigila-national",
                    )
                )
            for week, cases in (
                (date(2024, 1, 7), 2),
                (date(2024, 2, 4), 4),
                (date(2024, 2, 11), 5),
                (date(2024, 2, 18), 6),
                (date(2024, 2, 25), 7),
            ):
                session.add(
                    EpidemiologicalObservation(
                        municipality_code="99002",
                        disease="dengue",
                        week_start=week,
                        epidemiological_week=week.isocalendar().week,
                        epidemiological_year=week.year,
                        cases=cases,
                        source_id="sivigila-national",
                    )
                )
            await session.commit()

    asyncio.run(seed())
    sparse = client.get("/api/v1/analytics/summary?disease=dengue&territory=99001").json()
    assert sparse["comparison_gap_days"] == 56
    assert sparse["comparison_gap_weeks"] == 8
    assert sparse["comparison_comparable"] is False
    assert sparse["percent_change"] is None

    window = client.get("/api/v1/analytics/summary?disease=dengue&territory=99002").json()
    assert window["comparison_comparable"] is True
    four_weeks = window["windows"][0]
    assert four_weeks["observed_week_count"] == 4
    assert four_weeks["previous_observed_week_count"] == 1
    assert four_weeks["previous_missing_week_count"] == 3
    assert four_weeks["comparable"] is False
    assert four_weeks["percent_change_vs_previous"] is None


def test_forecast_series_falls_back_to_latest_champion_as_research_only(
    client: TestClient,
) -> None:
    cutoff = date.today() - timedelta(weeks=8)

    async def seed() -> None:
        async with client.app.state.session_factory() as session:
            session.add(
                Municipality(
                    code="54001",
                    name="Cucuta",
                    department_code="54",
                    department_name="Norte de Santander",
                )
            )
            model = ModelVersion(
                disease="zika",
                horizon_weeks=4,
                version="zika-retrospective",
                stage="champion",
                artifact_uri="models/zika-retrospective",
            )
            session.add(model)
            await session.flush()
            session.add(
                Forecast(
                    municipality_code="54001",
                    disease="zika",
                    issued_at=datetime.now(UTC) - timedelta(weeks=4),
                    target_week=date.today() - timedelta(days=1),
                    horizon_weeks=4,
                    predicted_cases=12,
                    interval_lower=7,
                    interval_upper=18,
                    outbreak_probability=0.75,
                    risk_level="high",
                    observation_cutoff=cutoff,
                    observation_age_days=(date.today() - cutoff).days,
                    operationally_eligible=True,
                    model_version_id=model.id,
                )
            )
            await session.commit()

    asyncio.run(seed())
    analytic = client.get(
        "/api/v1/analytics/forecast-series?disease=zika&territory=54001&horizon=4"
    )
    assert analytic.status_code == 200
    payload = analytic.json()
    assert payload["points"][0]["predicted_cases"] == 12
    assert payload["metadata"]["forecast_mode"] == "retrospective_research"
    assert payload["metadata"]["operationally_eligible"] is False
    assert payload["metadata"]["observation_cutoff"] == str(cutoff)
    assert "no para alertas operativas" in payload["metadata"]["message"]
    risk_map = client.get("/api/v1/risk/map?disease=zika&horizon=4").json()
    assert len(risk_map) == 1
    assert risk_map[0]["cod_dane"] == "54001"
    assert risk_map[0]["forecast_mode"] == "retrospective_research"
    assert risk_map[0]["operationally_eligible"] is False
    assert (
        client.get("/api/v1/risk/map?disease=zika&horizon=4&include_research=false").json()
        == []
    )


def test_current_bes_reference_prefers_latest_ingested_correction(client: TestClient) -> None:
    async def seed() -> None:
        async with client.app.state.session_factory() as session:
            sources = [
                DataSource(
                    id="bes-correction-a",
                    name="BES original",
                    institution="INS",
                    source_type="pdf",
                    status="active",
                ),
                DataSource(
                    id="bes-correction-b",
                    name="BES corregido",
                    institution="INS",
                    source_type="pdf",
                    status="active",
                ),
            ]
            session.add_all(sources)
            await session.flush()
            runs = [
                IngestionRun(source_id=source.id, status="succeeded") for source in sources
            ]
            session.add_all(runs)
            await session.flush()
            common = {
                "territory_code": "05",
                "territory_name": "Antioquia",
                "territory_level": "department",
                "disease": "dengue",
                "event_label": "Dengue",
                "epidemiological_year": 2026,
                "epidemiological_week": 26,
                "period_start": date(2026, 1, 1),
                "period_end": date(2026, 7, 4),
                "expected_cases": 90,
                "observed_cases": 100,
                "comparison_basis": "BES",
                "is_preliminary": True,
                "source_document_url": "https://example.org/bes.pdf",
                "source_page": 1,
            }
            session.add_all(
                [
                    EpidemiologicalBulletinAggregate(
                        **common,
                        cumulative_cases=100,
                        source_id=sources[0].id,
                        ingestion_run_id=runs[0].id,
                        created_at=datetime(2026, 7, 5, tzinfo=UTC),
                    ),
                    EpidemiologicalBulletinAggregate(
                        **common,
                        cumulative_cases=125,
                        source_id=sources[1].id,
                        ingestion_run_id=runs[1].id,
                        created_at=datetime(2026, 7, 6, tzinfo=UTC),
                    ),
                ]
            )
            await session.commit()

    asyncio.run(seed())
    response = client.get(
        "/api/v1/analytics/current-reference?disease=dengue&territory=05"
    )
    assert response.status_code == 200
    assert response.json()["cumulative_cases"] == 125
    assert response.json()["source_name"] == "BES corregido"
