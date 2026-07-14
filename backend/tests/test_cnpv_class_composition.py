from __future__ import annotations

import asyncio
from datetime import date

import httpx
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.connectors.dane import DANECNPVConnector
from app.jobs.dataset import build_training_dataset
from app.models.epidemiology import (
    EpidemiologicalObservation,
    Municipality,
    PipelineStatus,
    SocioeconomicIndicator,
)
from app.schemas.sources import SourceSyncRequest
from app.services.source_sync import process_source_sync, schedule_source_sync


def _municipal_row() -> dict[str, object]:
    return {
        "OBJECTID": 1,
        "DPTO_CCDGO": "76",
        "MPIO_CCDGO": "001",
        "MPIO_CDPMP": "76001",
        "STCTNENCUE": 400,
        "TSP16_HOG": 390,
        "STP19_ACU1": 360,
        "STP19_ACU2": 40,
        "STP19_ALC1": 320,
        "STP19_ALC2": 80,
        "STP27_PERS": 1000,
    }


def _class_rows() -> list[dict[str, object]]:
    return [
        {
            "OBJECTID": class_code,
            "DPTO_CCDGO": "76",
            "MPIO_CCDGO": "001",
            "MPIO_CDPMP": "76001",
            "CLAS_CCDGO": str(class_code),
            "Clase": label,
            "STP27_PERS": population,
        }
        for class_code, label, population in (
            (1, "Cabecera municipal", 700),
            (2, "Centro poblado", 200),
            (3, "Area resto municipal", 100),
        )
    ]


def test_cnpv_connector_uses_distinct_official_layers() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["returnGeometry"] == "false"
        if request.url.path.endswith("/800/query"):
            assert "STP19_ACU1" in request.url.params["outFields"]
            return httpx.Response(
                200,
                json={"features": [{"attributes": _municipal_row()}]},
                request=request,
            )
        assert request.url.path.endswith("/801/query")
        assert "CLAS_CCDGO" in request.url.params["outFields"]
        return httpx.Response(
            200,
            json={"features": [{"attributes": row} for row in _class_rows()]},
            request=request,
        )

    async def run() -> tuple[list[dict], list[dict]]:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            connector = DANECNPVConnector(client)
            return (
                await connector.fetch_municipal_indicators(),
                await connector.fetch_class_indicators(),
            )

    municipal, classes = asyncio.run(run())
    assert municipal[0]["MPIO_CDPMP"] == "76001"
    assert [row["CLAS_CCDGO"] for row in classes] == ["1", "2", "3"]


def test_cnpv_sync_persists_traceable_class_composition_and_dataset_features(
    client: TestClient,
    tmp_path,
) -> None:
    client.app.state.settings.raw_snapshot_dir = str(tmp_path / "raw")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/800/query"):
            features = [{"attributes": _municipal_row()}]
        elif request.url.path.endswith("/801/query"):
            features = [{"attributes": row} for row in _class_rows()]
        else:
            raise AssertionError(f"Unexpected CNPV URL: {request.url}")
        return httpx.Response(200, json={"features": features}, request=request)

    async def exercise() -> tuple:
        factory = client.app.state.session_factory
        async with factory() as session:
            session.add(
                Municipality(
                    code="76001",
                    name="Cali",
                    department_code="76",
                    department_name="Valle del Cauca",
                )
            )
            await session.commit()
            run = await schedule_source_sync(
                session,
                "dane-socioeconomic",
                SourceSyncRequest(),
            )
            async with httpx.AsyncClient(
                transport=httpx.MockTransport(handler)
            ) as http_client:
                completed = await process_source_sync(
                    session,
                    run,
                    client.app.state.settings,
                    http_client=http_client,
                )
            indicator = await session.scalar(select(SocioeconomicIndicator))
            municipality = await session.get(Municipality, "76001")
            assert indicator is not None and municipality is not None
            session.add_all(
                [
                    EpidemiologicalObservation(
                        municipality_code="76001",
                        disease="dengue",
                        week_start=week,
                        epidemiological_week=week.isocalendar().week,
                        epidemiological_year=week.year,
                        cases=cases,
                        source_id="sivigila-national",
                    )
                    for week, cases in (
                        (date(2022, 1, 2), 3),
                        (date(2022, 1, 9), 4),
                    )
                ]
            )
            await session.commit()
            dataset = await build_training_dataset(session, "dengue")
            return completed, indicator, municipality, dataset

    completed, indicator, municipality, dataset = asyncio.run(exercise())
    assert completed.status == PipelineStatus.SUCCEEDED.value
    assert completed.rows_read == 4
    assert completed.rows_accepted == 4
    assert completed.quality_report["canonical_rows"] == 1
    assert completed.quality_report["municipalities_with_class_composition"] == 1
    assert completed.quality_report["urban_rural_policy"].startswith("urban=class 1")
    assert completed.quality_report["municipalities_without_class_composition"] == 0
    assert indicator.water_access_pct == 90
    assert indicator.sewer_access_pct == 80
    assert indicator.urban_population_pct == 70
    assert indicator.rural_population_pct == 30
    assert indicator.populated_center_population_pct == 20
    assert indicator.rural_remainder_population_pct == 10
    assert municipality.population == 1000
    assert set(dataset.frame["urban_population_pct"].dropna()) == {70}
    assert set(dataset.frame["rural_population_pct"].dropna()) == {30}
    semantics = dataset.manifest["feature_semantics"]
    assert semantics["urban_population_pct"]["source"] == "DANE CNPV 2018 layer 801"
