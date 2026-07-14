from __future__ import annotations

import asyncio
from datetime import date

from fastapi.testclient import TestClient

from app.models.epidemiology import EpidemiologicalObservation, Municipality

DISEASE_TERRITORIES = (
    ("dengue", "76001", "Cali", "76", "Valle del Cauca"),
    ("malaria", "27001", "Quibdo", "27", "Choco"),
    ("chikunguna", "05001", "Medellin", "05", "Antioquia"),
    ("zika", "41001", "Neiva", "41", "Huila"),
    ("leishmaniasis", "50001", "Villavicencio", "50", "Meta"),
    ("ira", "11001", "Bogota", "11", "Bogota D.C."),
)


def test_historical_catalog_keeps_all_diseases_available_without_operational_forecasts(
    client: TestClient,
) -> None:
    """Changing disease must not make its observed territories disappear.

    Historical availability is a different contract from the operational risk
    map.  This is the regression that previously left the dashboard selector
    empty whenever no current forecast passed the publication gate.
    """

    async def seed() -> None:
        factory = client.app.state.session_factory
        async with factory() as session:
            for index, (
                _,
                code,
                municipality,
                department_code,
                department,
            ) in enumerate(DISEASE_TERRITORIES):
                session.add(
                    Municipality(
                        code=code,
                        name=municipality,
                        department_code=department_code,
                        department_name=department,
                        population=100_000 + index,
                        latitude=4.0 + index,
                        longitude=-75.0 + index,
                    )
                )
            await session.flush()

            for index, (disease, code, _, _, _) in enumerate(DISEASE_TERRITORIES):
                session.add_all(
                    [
                        EpidemiologicalObservation(
                            municipality_code=code,
                            disease=disease,
                            week_start=date(2021, 1, 3),
                            epidemiological_week=1,
                            epidemiological_year=2021,
                            cases=index + 1,
                            quality_score=0.8,
                            is_preliminary=False,
                            source_id="sivigila-national",
                        ),
                        EpidemiologicalObservation(
                            municipality_code=code,
                            disease=disease,
                            week_start=date(2022, 12, 25),
                            epidemiological_week=52,
                            epidemiological_year=2022,
                            cases=index + 11,
                            quality_score=0.9,
                            is_preliminary=True,
                            source_id="sivigila-national",
                        ),
                    ]
                )
            await session.commit()

    asyncio.run(seed())

    for index, (disease, code, municipality, _, department) in enumerate(
        DISEASE_TERRITORIES
    ):
        risk_map = client.get(f"/api/v1/risk/map?disease={disease}&horizon=4")
        assert risk_map.status_code == 200
        assert risk_map.json() == []

        response = client.get(
            f"/api/v1/analytics/historical-territories?disease={disease}"
        )
        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["disease"] == disease
        assert payload["total"] == 1
        assert payload["metadata"]["data_kind"] == "historical_observations"
        assert payload["metadata"]["risk_included"] is False
        assert payload["metadata"]["forecast_eligibility_required"] is False

        item = payload["items"][0]
        assert item["cod_dane"] == code
        assert item["municipality"] == municipality
        assert item["department"] == department
        assert item["first_week"] == "2021-01-03"
        assert item["latest_week"] == "2022-12-25"
        assert item["observation_rows"] == 2
        assert item["latest_observed_cases"] == index + 11
        assert item["total_observed_cases"] == (index + 1) + (index + 11)
        assert item["latest_is_preliminary"] is True
        assert item["latest_quality_score"] == 0.9


def test_historical_catalog_empty_state_is_not_an_api_failure(client: TestClient) -> None:
    response = client.get(
        "/api/v1/analytics/historical-territories?disease=leishmaniasis"
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["disease"] == "leishmaniasis"
    assert payload["total"] == 0
    assert payload["items"] == []
    assert payload["metadata"]["status"] == "no_data"
    assert payload["metadata"]["data_kind"] == "historical_observations"
    assert payload["metadata"]["risk_included"] is False
    assert payload["metadata"]["forecast_eligibility_required"] is False
    assert payload["metadata"]["synthetic_values"] is False
    assert payload["metadata"]["returned"] == 0
