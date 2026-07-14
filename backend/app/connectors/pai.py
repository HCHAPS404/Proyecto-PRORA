"""MinSalud PAI administrative coverage by department connector."""

from __future__ import annotations

import os
from dataclasses import dataclass

from .base import SocrataSourceConnector
from .socrata import Filter, Operator, SafeQuery, SocrataClient

DEFAULT_PAI_DATASET_ID = "6i25-2hdt"


@dataclass(slots=True)
class PAIConnector(SocrataSourceConnector):
    def __init__(
        self,
        client: SocrataClient,
        dataset_id: str | None = None,
        page_size: int = 5_000,
    ):
        SocrataSourceConnector.__init__(
            self,
            client=client,
            dataset_id=dataset_id or os.getenv("PRORA_PAI_DATASET_ID", DEFAULT_PAI_DATASET_ID),
            source_name="MinSalud PAI por departamento",
            page_size=page_size,
        )

    @staticmethod
    def query(
        *,
        year_from: int | None = None,
        year_to: int | None = None,
        biologics: tuple[str, ...] = (),
    ) -> SafeQuery:
        filters: list[Filter] = []
        if year_from is not None:
            filters.append(Filter("a_o", Operator.GTE, year_from))
        if year_to is not None:
            filters.append(Filter("a_o", Operator.LTE, year_to))
        if biologics:
            filters.append(Filter("biol_gico", Operator.IN, biologics))
        return SafeQuery(
            select=(
                ":id",
                "coddepto",
                "departamento",
                "a_o",
                "biol_gico",
                "cobertura_de_vacunaci_n",
            ),
            filters=tuple(filters),
            order_by=(
                ("a_o", "ASC"),
                ("coddepto", "ASC"),
                ("biol_gico", "ASC"),
                (":id", "ASC"),
            ),
        )
