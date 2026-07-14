"""INS national *aggregated* weekly SIVIGILA publication (not patient microdata)."""

from __future__ import annotations

import os
from dataclasses import dataclass

from .base import SocrataSourceConnector
from .socrata import Filter, Operator, SafeQuery, SocrataClient

DEFAULT_SIVIGILA_DATASET_ID = "4hyg-wa9d"

# Verified against the official INS publication. Mortality events 540/580 are
# deliberately excluded; IRAG 348 is retained only as an explicit IRA proxy.
PRIORITIZED_EVENT_CODES: dict[str, tuple[int, ...]] = {
    "dengue": (210, 220),
    "chikunguna": (217,),
    "ira": (348,),
    "leishmaniasis": (420, 430, 440),
    "malaria": (460, 470, 480, 490, 495),
    "zika": (895,),
}
EVENT_TO_DISEASE = {
    event_code: disease
    for disease, event_codes in PRIORITIZED_EVENT_CODES.items()
    for event_code in event_codes
}


@dataclass(slots=True)
class SIVIGILAConnector(SocrataSourceConnector):
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
            or os.getenv("PRORA_SIVIGILA_DATASET_ID", DEFAULT_SIVIGILA_DATASET_ID),
            source_name="INS SIVIGILA agregado semanal",
            page_size=page_size,
        )

    @staticmethod
    def query(
        *,
        year_from: int | None = None,
        year_to: int | None = None,
        event_codes: tuple[int, ...] = tuple(sorted(EVENT_TO_DISEASE)),
    ) -> SafeQuery:
        filters: list[Filter] = []
        if year_from is not None:
            filters.append(Filter("ano", Operator.GTE, year_from))
        if year_to is not None:
            filters.append(Filter("ano", Operator.LTE, year_to))
        if event_codes:
            filters.append(Filter("cod_eve", Operator.IN, event_codes))
        return SafeQuery(
            select=(
                ":id",
                "cod_eve",
                "nombre_evento",
                "semana",
                "ano",
                "cod_dpto_o",
                "cod_mun_o",
                "departamento_ocurrencia",
                "municipio_ocurrencia",
                "conteo",
            ),
            filters=tuple(filters),
            order_by=(
                ("ano", "ASC"),
                ("semana", "ASC"),
                ("cod_mun_o", "ASC"),
                ("cod_eve", "ASC"),
                (":id", "ASC"),
            ),
        )
