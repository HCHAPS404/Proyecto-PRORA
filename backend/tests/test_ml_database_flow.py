from __future__ import annotations

import asyncio
from datetime import date, timedelta
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.jobs.dataset import build_training_dataset, persist_training_dataset
from app.jobs.training import process_training_job
from app.ml.config import MLConfig
from app.models.epidemiology import (
    ClimateObservation,
    DataSource,
    DepartmentVaccinationCoverage,
    EpidemiologicalObservation,
    Forecast,
    IngestionRun,
    ModelTrainingRun,
    ModelVersion,
    Municipality,
    PipelineStatus,
    SocioeconomicIndicator,
    SourceStatus,
    VaccinationCoverage,
)


async def _ensure_sources(session) -> None:
    sources = (
        ("sivigila-national", "SIVIGILA nacional", "INS"),
        ("pai-national", "PAI nacional", "Ministerio de Salud"),
        ("pai-municipal-history", "PAI municipal", "Ministerio de Salud"),
        ("dane-socioeconomic", "DANE socioeconomico", "DANE"),
        ("ideam-climate", "IDEAM clima", "IDEAM"),
    )
    for source_id, name, institution in sources:
        if await session.get(DataSource, source_id) is None:
            session.add(
                DataSource(
                    id=source_id,
                    name=name,
                    institution=institution,
                    source_type="datos.gov.co",
                    status=SourceStatus.ACTIVE.value,
                )
            )
    await session.flush()


def test_database_dataset_is_calendarized_and_department_vaccination_is_explicit(
    client: TestClient,
    tmp_path: Path,
) -> None:
    async def build():
        factory = client.app.state.session_factory
        async with factory() as session:
            await _ensure_sources(session)
            session.add_all(
                [
                    Municipality(
                        code="05001",
                        name="Medellin",
                        department_code="05",
                        department_name="Antioquia",
                        population=2_500_000,
                    ),
                    Municipality(
                        code="05002",
                        name="Abejorral",
                        department_code="05",
                        department_name="Antioquia",
                        population=20_000,
                    ),
                ]
            )
            run = IngestionRun(
                source_id="pai-national",
                status=PipelineStatus.SUCCEEDED.value,
            )
            session.add(run)
            municipal_run = IngestionRun(
                source_id="pai-municipal-history",
                status=PipelineStatus.SUCCEEDED.value,
            )
            session.add(municipal_run)
            await session.flush()
            session.add(
                DepartmentVaccinationCoverage(
                    department_code="05",
                    department_name="Antioquia",
                    year=2025,
                    vaccine="bcg",
                    source_vaccine_label="BCG",
                    coverage_pct=83.5,
                    source_id="pai-national",
                    ingestion_run_id=run.id,
                    raw_record_sha256="a" * 64,
                )
            )
            session.add(
                SocioeconomicIndicator(
                    municipality_code="05001",
                    year=2024,
                    water_access_pct=91.2,
                    sewer_access_pct=88.4,
                    overcrowding_pct=8.1,
                    nbi_pct=7.5,
                    urban_population_pct=78.0,
                    rural_population_pct=22.0,
                    source_id="dane-socioeconomic",
                )
            )
            session.add(
                VaccinationCoverage(
                    municipality_code="05001",
                    year=2024,
                    month=12,
                    vaccine="influenza_6_11m_second_dose",
                    source_vaccine_label="Influenza segunda dosis 6-11 meses",
                    period_semantics="cumulative_cutoff",
                    coverage_pct=72.0,
                    source_id="pai-municipal-history",
                    ingestion_run_id=municipal_run.id,
                )
            )
            for municipality in ("05001", "05002"):
                for week, cases in ((date(2025, 1, 5), 10), (date(2025, 1, 19), 14)):
                    session.add(
                        EpidemiologicalObservation(
                            municipality_code=municipality,
                            disease="dengue",
                            week_start=week,
                            epidemiological_week=week.isocalendar().week,
                            epidemiological_year=week.year,
                            cases=cases,
                            population=None,
                            is_preliminary=False,
                            quality_score=0.98,
                            source_id="sivigila-national",
                        )
                    )
            await session.commit()

        async with factory() as session:
            first = await build_training_dataset(session, "dengue")
            second = await build_training_dataset(session, "dengue")
            return first, second

    first, second = asyncio.run(build())
    assert first.fingerprint == second.fingerprint
    assert len(first.frame) == 6
    assert first.frame["cases"].isna().sum() == 2
    assert set(first.frame["pai_proxy_territory_level"].dropna()) == {
        "department",
        "municipality",
    }
    assert set(first.frame["pai_program_coverage_bcg"].dropna()) == {83.5}
    assert set(
        first.frame.loc[
            first.frame["territory_id"] == "05001",
            "pai_health_system_access_proxy",
        ].dropna()
    ) == {72.0}
    assert set(
        first.frame.loc[
            first.frame["territory_id"] == "05002",
            "pai_health_system_access_proxy",
        ].dropna()
    ) == {83.5}
    assert set(first.frame.loc[first.frame["territory_id"] == "05001", "water_access"]) == {91.2}
    assert first.manifest["covariate_granularity"]["pai_health_system_access_proxy"].startswith(
        "municipality"
    )
    assert first.manifest["covariate_coverage"]["pai_municipal"]["status"] in {
        "partial",
        "available",
    }
    assert any(item["covariate"] == "urban_rural" for item in first.manifest["known_data_gaps"])
    assert set(
        first.frame.loc[first.frame["territory_id"] == "05001", "urban_population_pct"].dropna()
    ) == {78.0}
    assert (
        first.manifest["feature_semantics"]["pai_health_system_access_proxy"][
            "causal_interpretation"
        ]
        is False
    )

    first_snapshot = persist_training_dataset(first, tmp_path / "registry")
    second_snapshot = persist_training_dataset(second, tmp_path / "registry")
    assert first_snapshot.sha256 == second_snapshot.sha256
    assert Path(first_snapshot.uri).is_file()

    summary = client.get("/api/v1/analytics/summary?disease=dengue&territory=05")
    assert summary.status_code == 200
    department_summary = summary.json()
    assert department_summary["latest"]["observed_cases"] == 28
    assert department_summary["data_status"] == "stale"
    assert department_summary["windows"][0] == {
        "weeks": 4,
        "from_week": "2024-12-29",
        "to_week": "2025-01-19",
        "observed_cases": 48,
        "observed_week_count": 2,
            "missing_week_count": 2,
            "previous_observed_cases": None,
            "previous_observed_week_count": 0,
            "previous_missing_week_count": 4,
            "comparable": False,
            "percent_change_vs_previous": None,
        "incidence_per_100k": 1.9048,
    }
    municipal_summary = client.get(
        "/api/v1/analytics/summary?disease=dengue&territory=05001"
    ).json()
    assert municipal_summary["scope"] == "municipality"
    assert municipal_summary["latest"]["observed_cases"] == 14
    assert municipal_summary["windows"][0]["observed_cases"] == 24
    assert municipal_summary["windows"][0]["incidence_per_100k"] == 0.96
    series = client.get("/api/v1/analytics/series?disease=dengue&territory=national")
    assert [point["observed_cases"] for point in series.json()["points"]] == [20, 28]
    readiness = client.get("/api/v1/models/readiness/portfolio")
    assert readiness.status_code == 200
    dengue = next(item for item in readiness.json()["diseases"] if item["disease"] == "dengue")
    assert dengue["operational_forecast_eligible"] is False
    assert "no_explicit_zero_case_reports" in dengue["limitations"]
    inventory = readiness.json()["covariate_inventory"]
    assert inventory["climate"]["status"] == "unavailable"
    assert inventory["climate"]["unique_weeks"] == 0
    assert inventory["urban_rural"]["status"] == "available"
    assert inventory["urban_rural"]["rows"] == 1


def test_training_job_persists_traceable_versions_and_operational_forecasts(
    client: TestClient,
    tmp_path: Path,
    monkeypatch,
) -> None:
    registry_path = tmp_path / "models"
    client.app.state.settings.model_registry_path = str(registry_path)
    small_config = MLConfig(
        min_train_weeks=32,
        validation_weeks=4,
        n_splits=2,
        territorial_splits=3,
        enable_lstm=False,
        rf_estimators=20,
        hgb_iterations=24,
        random_state=19,
        min_observed_training_rows=100,
        min_training_territories=3,
        min_training_weeks=52,
    )
    monkeypatch.setattr("app.jobs.training.MLConfig", lambda: small_config)

    async def run_training() -> tuple[str, int, int, str]:
        factory = client.app.state.session_factory
        latest_sunday = date.today() - timedelta(days=(date.today().weekday() + 1) % 7)
        start = latest_sunday - timedelta(weeks=69)
        territories = (
            ("05001", "Medellin", "05", "Antioquia", 2_500_000),
            ("11001", "Bogota", "11", "Bogota D.C.", 8_000_000),
            ("76001", "Cali", "76", "Valle del Cauca", 2_300_000),
        )
        async with factory() as session:
            await _ensure_sources(session)
            for code, name, department, department_name, population in territories:
                session.add(
                    Municipality(
                        code=code,
                        name=name,
                        department_code=department,
                        department_name=department_name,
                        population=population,
                    )
                )
                # SQLAlchemy does not have ORM relationships between these
                # bulk-loaded records; flush the referenced municipality before
                # inserting its observations so SQLite FK checks are deterministic.
                await session.flush()
                for offset in range(70):
                    week = start + timedelta(weeks=offset)
                    seasonal = (offset % 13) + int(department)
                    session.add(
                        EpidemiologicalObservation(
                            municipality_code=code,
                            disease="dengue",
                            week_start=week,
                            epidemiological_week=week.isocalendar().week,
                            epidemiological_year=week.year,
                            cases=10 + seasonal,
                            population=population,
                            is_preliminary=offset >= 68,
                            quality_score=0.97,
                            source_id="sivigila-national",
                        )
                    )
            job = ModelTrainingRun(
                disease="dengue",
                horizons=[3, 4],
                status=PipelineStatus.RUNNING.value,
                parameters={"force": True},
            )
            session.add(job)
            await session.commit()
            await session.refresh(job)
            job_id = job.id

        async with factory() as session:
            current_job = await session.get(ModelTrainingRun, job_id)
            assert current_job is not None
            await process_training_job(session, current_job, str(registry_path))

        async with factory() as session:
            stored_job = await session.get(ModelTrainingRun, job_id)
            model_count = await session.scalar(
                select(func.count(ModelVersion.id)).where(ModelVersion.stage == "champion")
            )
            forecast_count = await session.scalar(select(func.count(Forecast.id)))
            first_model = await session.scalar(
                select(ModelVersion).order_by(ModelVersion.horizon_weeks)
            )
            assert stored_job is not None
            assert first_model is not None
            return (
                stored_job.status,
                int(model_count or 0),
                int(forecast_count or 0),
                first_model.version,
            )

    job_status, model_count, forecast_count, version = asyncio.run(run_training())
    assert job_status == PipelineStatus.SUCCEEDED.value
    assert model_count == 2
    assert forecast_count == 6

    forecasts = client.get(
        "/api/v1/analytics/forecast-series?disease=dengue&territory=national&horizon=3"
    )
    assert forecasts.status_code == 200
    assert forecasts.json()["metadata"]["status"] == "retrospective_research"
    assert forecasts.json()["metadata"]["forecast_mode"] == "retrospective_research"
    assert forecasts.json()["metadata"]["operationally_eligible"] is False
    assert forecasts.json()["points"]

    risk_map = client.get("/api/v1/risk/map?disease=dengue&horizon=4")
    assert risk_map.status_code == 200
    assert risk_map.json() == []

    trace = client.get(f"/api/v1/models/dengue/3/versions/{version}/trace")
    assert trace.status_code == 200
    body = trace.json()
    assert body["artifact_integrity_valid"] is True
    assert body["artifact_sha256"]
    assert body["data_fingerprint"]
    assert body["dataset_snapshot_sha256"]
    assert body["seed"] == 19
    assert body["fold_metrics"]
    assert body["metrics"]["benchmark"]["passes_baseline_gate"] is False
    assert body["readiness"]["operational_forecast_eligible"] is True
    assert not any("snapshot_uri" in key for key in body["dataset"])


def test_training_failure_is_persisted_after_rollback_without_implicit_orm_refresh(
    client: TestClient,
    tmp_path: Path,
    monkeypatch,
) -> None:
    async def fail_dataset(*_args, **_kwargs):
        raise ValueError("forced dataset failure")

    monkeypatch.setattr("app.jobs.training.build_training_dataset", fail_dataset)

    async def run_failure() -> tuple[str, str | None]:
        factory = client.app.state.session_factory
        async with factory() as session:
            job = ModelTrainingRun(
                disease="dengue",
                horizons=[3, 4],
                status=PipelineStatus.RUNNING.value,
                parameters={"force": True},
            )
            session.add(job)
            await session.commit()
            await session.refresh(job)
            job_id = job.id

        async with factory() as session:
            current = await session.get(ModelTrainingRun, job_id)
            assert current is not None
            await process_training_job(session, current, str(tmp_path / "failed-models"))

        async with factory() as session:
            stored = await session.get(ModelTrainingRun, job_id)
            assert stored is not None
            return stored.status, stored.error_message

    status, error = asyncio.run(run_failure())
    assert status == PipelineStatus.FAILED.value
    assert error == "forced dataset failure"


def test_portfolio_marks_discontinuous_climate_as_partial(client: TestClient) -> None:
    async def seed() -> None:
        factory = client.app.state.session_factory
        async with factory() as session:
            await _ensure_sources(session)
            session.add(
                Municipality(
                    code="05001",
                    name="Medellin",
                    department_code="05",
                    department_name="Antioquia",
                )
            )
            await session.flush()
            run = IngestionRun(
                source_id="ideam-climate",
                status=PipelineStatus.SUCCEEDED.value,
            )
            session.add(run)
            await session.flush()
            for week in (date(2025, 1, 5), date(2025, 3, 16)):
                session.add(
                    ClimateObservation(
                        municipality_code="05001",
                        week_start=week,
                        precipitation_mm=10.0,
                        temperature_mean_c=24.0,
                        humidity_relative_pct=70.0,
                        source_id="ideam-climate",
                        ingestion_run_id=run.id,
                    )
                )
            await session.commit()

    asyncio.run(seed())
    response = client.get("/api/v1/models/readiness/portfolio")
    assert response.status_code == 200
    climate = response.json()["covariate_inventory"]["climate"]
    assert climate["status"] == "partial"
    assert climate["unique_weeks"] == 2
    assert climate["calendar_weeks_in_span"] == 11
    assert climate["precipitation_rows"] == 2
