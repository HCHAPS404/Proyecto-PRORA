"""IDEAM climate and deforestation source connectors."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime

from .base import SocrataSourceConnector
from .socrata import (
    Aggregate,
    Filter,
    Function,
    GroupExpression,
    Operator,
    SafeQuery,
    SelectExpression,
    SocrataClient,
)

DEFAULT_CLIMATE_DATASET_ID = "57sv-p2fu"
DEFAULT_STATIONS_DATASET_ID = "hp9r-jxuu"


@dataclass(slots=True)
class IDEAMClimateConnector(SocrataSourceConnector):
    def __init__(
        self,
        client: SocrataClient,
        dataset_id: str | None = None,
        page_size: int = 10_000,
    ):
        SocrataSourceConnector.__init__(
            self,
            client=client,
            dataset_id=dataset_id
            or os.getenv("PRORA_IDEAM_CLIMATE_DATASET_ID", DEFAULT_CLIMATE_DATASET_ID),
            source_name="IDEAM estaciones hidrometeorológicas",
            page_size=page_size,
        )

    @staticmethod
    def query(
        *,
        observed_from: datetime | None = None,
        sensor_codes: tuple[str, ...] = (),
        municipality: str | None = None,
    ) -> SafeQuery:
        filters: list[Filter] = []
        if observed_from is not None:
            filters.append(Filter("fechaobservacion", Operator.GTE, observed_from))
        if sensor_codes:
            filters.append(Filter("codigosensor", Operator.IN, sensor_codes))
        if municipality:
            filters.append(Filter("municipio", Operator.EQ, municipality))
        return SafeQuery(
            select=(
                ":id",
                "codigoestacion",
                "codigosensor",
                "fechaobservacion",
                "valorobservado",
                "nombreestacion",
                "departamento",
                "municipio",
                "zonahidrografica",
                "latitud",
                "longitud",
                "descripcionsensor",
                "unidadmedida",
                "entidad",
            ),
            filters=tuple(filters),
            order_by=(
                ("fechaobservacion", "ASC"),
                ("codigoestacion", "ASC"),
                ("codigosensor", "ASC"),
                (":id", "ASC"),
            ),
        )

    @staticmethod
    def daily_station_query(
        *,
        observed_from: datetime,
        observed_to: datetime,
        aggregation: Aggregate,
    ) -> SafeQuery:
        """Aggregate high-volume readings per station/day in SODA, then weekly locally."""
        return SafeQuery(
            select=(
                SelectExpression(
                    alias="observation_day",
                    field="fechaobservacion",
                    function=Function.DATE_TRUNC_YMD,
                ),
                "departamento",
                "municipio",
                "codigoestacion",
                SelectExpression(
                    alias="metric_value", field="valorobservado", aggregate=aggregation
                ),
                SelectExpression(alias="reading_count", aggregate=Aggregate.COUNT),
            ),
            filters=(
                Filter("fechaobservacion", Operator.GTE, observed_from),
                Filter("fechaobservacion", Operator.LT, observed_to),
            ),
            group_by=(
                GroupExpression("fechaobservacion", Function.DATE_TRUNC_YMD),
                "departamento",
                "municipio",
                "codigoestacion",
            ),
            order_by=(
                ("observation_day", "ASC"),
                ("departamento", "ASC"),
                ("municipio", "ASC"),
                ("codigoestacion", "ASC"),
            ),
        )


@dataclass(slots=True)
class IDEAMStationsConnector(SocrataSourceConnector):
    def __init__(
        self,
        client: SocrataClient,
        dataset_id: str | None = None,
        page_size: int = 5_000,
    ):
        SocrataSourceConnector.__init__(
            self,
            client=client,
            dataset_id=dataset_id
            or os.getenv("PRORA_IDEAM_STATIONS_DATASET_ID", DEFAULT_STATIONS_DATASET_ID),
            source_name="IDEAM Catálogo Nacional de Estaciones",
            page_size=page_size,
        )

    @staticmethod
    def query() -> SafeQuery:
        return SafeQuery(
            select=(
                ":id",
                "codigo",
                "nombre",
                "categoria",
                "tecnologia",
                "estado",
                "departamento",
                "municipio",
                "altitud",
                "longitud",
                "latitud",
                "fecha_instalacion",
                "fecha_suspension",
                "entidad",
            ),
            order_by=(("codigo", "ASC"), (":id", "ASC")),
        )


@dataclass(slots=True)
class IDEAMDeforestationConnector(SocrataSourceConnector):
    """Adapter for a validated table; official catalog entries are currently files."""

    def __init__(
        self,
        client: SocrataClient,
        dataset_id: str | None = None,
        page_size: int = 5_000,
    ):
        SocrataSourceConnector.__init__(
            self,
            client=client,
            dataset_id=dataset_id or os.getenv("PRORA_IDEAM_DEFORESTATION_DATASET_ID"),
            source_name="IDEAM deforestación",
            page_size=page_size,
        )

    @staticmethod
    def query(*, year_from: int | None = None) -> SafeQuery:
        year_field = os.getenv("PRORA_IDEAM_DEFORESTATION_YEAR_FIELD", "ano")
        filters = (Filter(year_field, Operator.GTE, year_from),) if year_from is not None else ()
        return SafeQuery(filters=filters, order_by=((year_field, "ASC"),))
