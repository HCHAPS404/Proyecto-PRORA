from __future__ import annotations

import asyncio

import httpx
import pytest

from app.connectors.dane import DIVIPOLAConnector
from app.connectors.errors import ConnectorConfigurationError
from app.connectors.ideam import IDEAMDeforestationConnector
from app.connectors.socrata import SocrataClient
from app.ingestion.divipola import DIVIPOLAIndex, territory
from app.ingestion.normalizers import (
    normalize_ideam_climate,
    normalize_pai,
    normalize_sivigila,
)


def test_normalize_sivigila_preserves_divipola_and_provenance() -> None:
    record, quality = normalize_sivigila(
        {
            "cod_eve": "210",
            "nombre_evento": "Dengue",
            "semana": "27",
            "ano": "2026",
            "cod_dpto_o": "76",
            "cod_mun_o": "834",
            "departamento_ocurrencia": "Valle del Cauca",
            "municipio_ocurrencia": "Tuluá",
            "conteo": "14",
        }
    )
    assert quality.valid
    assert record.territory.divipola_code == "76834"
    assert record.cases == 14
    assert len(record.provenance.raw_record_sha256) == 64


def test_normalize_pai_preserves_administrative_coverage_above_100_as_warning() -> None:
    record, quality = normalize_pai(
        {
            "coddepto": "11",
            "departamento": "Bogotá D.C.",
            "a_o": "2023",
            "biol_gico": "TV",
            "cobertura_de_vacunaci_n": "104.2",
        }
    )
    assert quality.valid
    assert record.quality_flags == ("administrative_coverage_above_100",)


def test_normalize_ideam_climate() -> None:
    record, quality = normalize_ideam_climate(
        {
            "codigoestacion": "0024035340",
            "codigosensor": "0071",
            "fechaobservacion": "2026-07-12T10:00:00.000",
            "valorobservado": "18.2",
            "descripcionsensor": "Temperatura del aire",
            "unidadmedida": "°C",
            "departamento": "Boyacá",
            "municipio": "Sogamoso",
            "latitud": "5.6769",
            "longitud": "-72.9679",
            "entidad": "IDEAM",
        }
    )
    assert quality.valid
    assert record.value == 18.2
    assert record.territory.municipality_name == "Sogamoso"


def test_unverified_deforestation_table_requires_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("PRORA_IDEAM_DEFORESTATION_DATASET_ID", raising=False)
    connector = IDEAMDeforestationConnector(SocrataClient())
    with pytest.raises(ConnectorConfigurationError):
        connector.require_dataset_id()


def test_divipola_arcgis_connector_and_index() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.params.get("returnIdsOnly") == "true":
            assert request.url.params["where"] == "1=1"
            return httpx.Response(200, json={"objectIds": [1601]}, request=request)
        assert request.url.params["returnGeometry"] == "true"
        assert request.url.params["maxAllowableOffset"] == "1000"
        return httpx.Response(
            200,
            json={
                "features": [
                    {
                        "attributes": {
                            "DPTO_CCDGO": "76",
                            "MPIO_CCDGO": "834",
                            "MPIO_CDPMP": "76834",
                            "DPTO_CNMBRE": "Valle del Cauca",
                            "MPIO_CNMBRE": "Tuluá",
                        },
                        "geometry": {
                            "rings": [
                                [
                                    [-8500000, 500000],
                                    [-8490000, 500000],
                                    [-8490000, 510000],
                                    [-8500000, 510000],
                                    [-8500000, 500000],
                                ]
                            ]
                        },
                    }
                ]
            },
            request=request,
        )

    async def run() -> list[dict[str, str]]:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await DIVIPOLAConnector(client).fetch_municipalities()

    rows = asyncio.run(run())
    index = DIVIPOLAIndex.from_arcgis(rows)
    resolved = index.resolve(
        territory(department_name="VALLE DEL CAUCA", municipality_name="Tulua")
    )
    assert resolved is not None
    assert resolved.divipola_code == "76834"
    assert 4 < rows[0]["_latitude"] < 5
    assert -77 < rows[0]["_longitude"] < -76
