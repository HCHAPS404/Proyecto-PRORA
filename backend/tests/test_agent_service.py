from __future__ import annotations

import asyncio
from datetime import date

from fastapi.testclient import TestClient

from app.agent.service import AgentService
from app.models.epidemiology import (
    DataSource,
    EpidemiologicalObservation,
    Municipality,
    SourceStatus,
)


def _facts() -> dict:
    return {
        "latest_observation": {
            "disease": "dengue",
            "week": "2022-12-25",
            "observed_cases": 1124,
            "municipalities_with_reports": 204,
            "mean_quality_score": 1.0,
            "is_preliminary": False,
            "source_ids": ["sivigila-national"],
        },
        "forecasts": [],
        "withheld_forecasts": 12,
        "models": [],
        "data_sources": [
            {
                "id": "sivigila-national",
                "name": "SIVIGILA histórico",
                "institution": "INS",
                "status": "active",
                "last_success_at": "2026-07-13T08:18:29+00:00",
            }
        ],
    }


def test_deterministic_agent_answers_latest_observation_without_calling_it_current() -> None:
    answer = AgentService._deterministic_answer(
        "¿Cuál es el último corte observado de dengue?", _facts()
    )

    assert "2022-12-25" in answer
    assert "1.124 casos" in answer
    assert "204 municipios" in answer
    assert "observación histórica" in answer
    assert "no una predicción actual" in answer
    assert "sivigila-national" in answer


def test_deterministic_agent_reports_synchronized_sources_from_grounded_facts() -> None:
    answer = AgentService._deterministic_answer(
        "¿Qué fuentes y datasets están conectados por API?", _facts()
    )

    assert "1 de 1 fuentes activas" in answer
    assert "1 ya registran una sincronización exitosa" in answer
    assert "INS (SIVIGILA histórico)" in answer
    assert "SHA-256" in answer


def test_agent_applies_selected_municipality_context(client: TestClient) -> None:
    async def seed() -> None:
        async with client.app.state.session_factory() as session:
            session.add(
                DataSource(
                    id="agent-sivigila",
                    name="SIVIGILA agregado",
                    institution="INS",
                    source_type="institutional-file",
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
                        code="76520",
                        name="Palmira",
                        department_code="76",
                        department_name="Valle del Cauca",
                    ),
                ]
            )
            await session.flush()
            session.add_all(
                [
                    EpidemiologicalObservation(
                        municipality_code="76001",
                        disease="dengue",
                        week_start=date(2024, 12, 22),
                        epidemiological_week=52,
                        epidemiological_year=2024,
                        cases=17,
                        source_id="agent-sivigila",
                    ),
                    EpidemiologicalObservation(
                        municipality_code="76520",
                        disease="dengue",
                        week_start=date(2024, 12, 22),
                        epidemiological_week=52,
                        epidemiological_year=2024,
                        cases=900,
                        source_id="agent-sivigila",
                    ),
                ]
            )
            await session.commit()

    asyncio.run(seed())
    response = client.post(
        "/api/v1/agent/query",
        json={
            "question": "¿Cuál es el último corte observado?",
            "context": {"disease": "dengue", "territory_code": "76001"},
        },
    )

    assert response.status_code == 200
    answer = response.json()["answer"]
    assert "Cali, Valle del Cauca" in answer
    assert "17 casos" in answer
    assert "territorio seleccionado" in answer
    assert "917" not in answer
