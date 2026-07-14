"""DANE socioeconomic and official DIVIPOLA ArcGIS connectors."""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from math import atan, exp, pi
from typing import Any

import httpx

from .base import SocrataSourceConnector
from .errors import ConnectorError
from .socrata import Filter, Operator, SafeQuery, SocrataClient

DIVIPOLA_MUNICIPALITIES_URL = (
    "https://geoportal.dane.gov.co/mparcgis/rest/services/Divipola/"
    "Serv_DIVIPOLA_MGN_2025/FeatureServer/317/query"
)
CNPV_MUNICIPAL_INDICATORS_URL = (
    "https://geoportal.dane.gov.co/mparcgis/rest/services/MARCO_INTEGRADO/"
    "Serv_DatosCNPV2018_Integrados_MGN2018/MapServer/800/query"
)
CNPV_CLASS_INDICATORS_URL = (
    "https://geoportal.dane.gov.co/mparcgis/rest/services/MARCO_INTEGRADO/"
    "Serv_DatosCNPV2018_Integrados_MGN2018/MapServer/801/query"
)


@dataclass(slots=True)
class DANEConnector(SocrataSourceConnector):
    """Configurable SODA connector for a selected DANE socioeconomic table."""

    def __init__(
        self,
        client: SocrataClient,
        dataset_id: str | None = None,
        page_size: int = 5_000,
    ):
        SocrataSourceConnector.__init__(
            self,
            client=client,
            dataset_id=dataset_id or os.getenv("PRORA_DANE_SOCIOECONOMIC_DATASET_ID"),
            source_name="DANE socioeconómico",
            page_size=page_size,
        )

    @staticmethod
    def query(*, year_from: int | None = None) -> SafeQuery:
        year_field = os.getenv("PRORA_DANE_YEAR_FIELD", "ano")
        filters = (Filter(year_field, Operator.GTE, year_from),) if year_from is not None else ()
        return SafeQuery(filters=filters, order_by=((year_field, "ASC"),))


@dataclass(slots=True)
class DIVIPOLAConnector:
    client: httpx.AsyncClient
    endpoint: str = DIVIPOLA_MUNICIPALITIES_URL

    async def fetch_municipalities(self, page_size: int = 50) -> list[dict[str, Any]]:
        # The public ArcGIS gateway intermittently times out for geometry batches
        # around 200 features. Small deterministic batches plus bounded retries
        # are slower, but make the national directory reproducible in practice.
        id_response = await _arcgis_get(
            self.client,
            self.endpoint,
            params={"where": "1=1", "returnIdsOnly": "true", "f": "json"},
        )
        id_payload = id_response.json()
        if "error" in id_payload:
            raise ConnectorError(f"DANE DIVIPOLA ID service error: {id_payload['error']}")
        object_ids = id_payload.get("objectIds")
        if not isinstance(object_ids, list):
            raise ConnectorError("Unexpected DANE DIVIPOLA objectIds response")
        object_ids = sorted(int(value) for value in object_ids)
        rows: list[dict[str, Any]] = []
        for offset in range(0, len(object_ids), page_size):
            page_ids = object_ids[offset : offset + page_size]
            response = await _arcgis_get(
                self.client,
                self.endpoint,
                params={
                    "objectIds": ",".join(str(value) for value in page_ids),
                    "outFields": (
                        "OBJECTID,DPTO_CCDGO,MPIO_CCDGO,MPIO_CDPMP,MPIO_TIPO,"
                        "MPIO_NANO,DPTO_CNMBRE,MPIO_CNMBRE"
                    ),
                    "returnGeometry": "true",
                    "maxAllowableOffset": "1000",
                    "orderByFields": "OBJECTID ASC",
                    "f": "json",
                },
            )
            payload = response.json()
            if "error" in payload:
                raise ConnectorError(f"DANE DIVIPOLA service error: {payload['error']}")
            features = payload.get("features")
            if not isinstance(features, list):
                raise ConnectorError("Unexpected DANE DIVIPOLA response shape")
            page: list[dict[str, Any]] = []
            for feature in features:
                if not isinstance(feature, dict) or not isinstance(
                    feature.get("attributes"), dict
                ):
                    continue
                attributes = dict(feature["attributes"])
                geometry = feature.get("geometry")
                if isinstance(geometry, dict):
                    attributes["_geometry"] = geometry
                    center = web_mercator_polygon_center(geometry)
                    if center is not None:
                        attributes["_longitude"], attributes["_latitude"] = center
                page.append(attributes)
            rows.extend(page)
        if len(rows) != len(object_ids):
            raise ConnectorError(
                f"DANE DIVIPOLA returned {len(rows)} features for {len(object_ids)} IDs"
            )
        return rows


@dataclass(slots=True)
class DANECNPVConnector:
    client: httpx.AsyncClient
    endpoint: str = CNPV_MUNICIPAL_INDICATORS_URL
    class_endpoint: str = CNPV_CLASS_INDICATORS_URL

    async def fetch_municipal_indicators(
        self, page_size: int = 1_000
    ) -> list[dict[str, Any]]:
        return await self._fetch_features(
            self.endpoint,
            (
                "OBJECTID,DPTO_CCDGO,MPIO_CCDGO,MPIO_CDPMP,STCTNENCUE,"
                "TSP16_HOG,STP19_ACU1,STP19_ACU2,STP19_ALC1,STP19_ALC2,STP27_PERS"
            ),
            page_size,
        )

    async def fetch_class_indicators(
        self, page_size: int = 1_000
    ) -> list[dict[str, Any]]:
        """Fetch official DANE population by territorial class (layer 801)."""

        return await self._fetch_features(
            self.class_endpoint,
            (
                "OBJECTID,DPTO_CCDGO,MPIO_CCDGO,MPIO_CDPMP,CLAS_CCDGO,"
                "Clase,STP27_PERS"
            ),
            page_size,
        )

    async def _fetch_features(
        self,
        endpoint: str,
        out_fields: str,
        page_size: int,
    ) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        offset = 0
        while True:
            response = await self.client.get(
                endpoint,
                params={
                    "where": "OBJECTID > 0",
                    "outFields": out_fields,
                    "returnGeometry": "false",
                    "orderByFields": "OBJECTID ASC",
                    "resultOffset": str(offset),
                    "resultRecordCount": str(page_size),
                    "f": "json",
                },
                headers={
                    "Accept": "application/json",
                    "User-Agent": "PRORA/1.0 (+public-health-research)",
                },
            )
            response.raise_for_status()
            payload = response.json()
            if "error" in payload:
                raise ConnectorError(f"DANE CNPV service error: {payload['error']}")
            features = payload.get("features")
            if not isinstance(features, list):
                raise ConnectorError("Unexpected DANE CNPV response shape")
            page = [
                feature["attributes"]
                for feature in features
                if isinstance(feature, dict) and isinstance(feature.get("attributes"), dict)
            ]
            rows.extend(page)
            offset += len(page)
            if len(page) < page_size and not payload.get("exceededTransferLimit"):
                return rows
            if not page:
                return rows


def _arcgis_headers() -> dict[str, str]:
    return {
        "Accept": "application/json",
        "User-Agent": "PRORA/1.0 (+public-health-research)",
    }


async def _arcgis_get(
    client: httpx.AsyncClient,
    endpoint: str,
    *,
    params: dict[str, str],
    max_retries: int = 4,
) -> httpx.Response:
    """GET an ArcGIS page with bounded retry for gateway/transient failures."""

    retryable = {408, 425, 429, 500, 502, 503, 504}
    last_error: Exception | None = None
    for attempt in range(max_retries + 1):
        try:
            response = await client.get(endpoint, params=params, headers=_arcgis_headers())
            if response.status_code not in retryable:
                response.raise_for_status()
                return response
            last_error = httpx.HTTPStatusError(
                f"Retryable ArcGIS status {response.status_code}",
                request=response.request,
                response=response,
            )
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            last_error = exc
        if attempt < max_retries:
            await asyncio.sleep(min(0.75 * (2**attempt), 6.0))
    raise ConnectorError(
        f"ArcGIS request failed after {max_retries + 1} attempts: {endpoint}"
    ) from last_error


def web_mercator_polygon_center(geometry: dict[str, Any]) -> tuple[float, float] | None:
    """Return a stable marker point from simplified EPSG:3857 polygon rings."""
    rings = geometry.get("rings")
    if not isinstance(rings, list) or not rings:
        return None
    usable = [
        [(float(point[0]), float(point[1])) for point in ring]
        for ring in rings
        if isinstance(ring, list)
        and len(ring) >= 3
        and all(isinstance(point, list | tuple) and len(point) >= 2 for point in ring)
    ]
    if not usable:
        return None
    ring = max(usable, key=lambda item: abs(_signed_area(item)))
    center = _ring_centroid(ring)
    if center is None or not _point_in_ring(center, ring):
        center = ring[0]
    return _web_mercator_to_wgs84(*center)


def _signed_area(ring: list[tuple[float, float]]) -> float:
    return sum(
        x1 * y2 - x2 * y1
        for (x1, y1), (x2, y2) in zip(ring, [*ring[1:], ring[0]], strict=True)
    ) / 2


def _ring_centroid(ring: list[tuple[float, float]]) -> tuple[float, float] | None:
    cross = [
        x1 * y2 - x2 * y1
        for (x1, y1), (x2, y2) in zip(ring, [*ring[1:], ring[0]], strict=True)
    ]
    denominator = 3 * sum(cross)
    if not denominator:
        return None
    x = sum(
        (first[0] + second[0]) * value
        for first, second, value in zip(ring, [*ring[1:], ring[0]], cross, strict=True)
    ) / denominator
    y = sum(
        (first[1] + second[1]) * value
        for first, second, value in zip(ring, [*ring[1:], ring[0]], cross, strict=True)
    ) / denominator
    return x, y


def _point_in_ring(point: tuple[float, float], ring: list[tuple[float, float]]) -> bool:
    x, y = point
    inside = False
    previous = ring[-1]
    for current in ring:
        x1, y1 = previous
        x2, y2 = current
        if (y1 > y) != (y2 > y):
            boundary_x = (x2 - x1) * (y - y1) / (y2 - y1) + x1
            if x < boundary_x:
                inside = not inside
        previous = current
    return inside


def _web_mercator_to_wgs84(x: float, y: float) -> tuple[float, float]:
    radius = 6_378_137.0
    longitude = x / radius * 180 / pi
    latitude = (2 * atan(exp(y / radius)) - pi / 2) * 180 / pi
    return longitude, latitude
