"""Verified public SIVIGILA 2024 workbook catalogue.

The INS portal publishes annual, anonymised event workbooks in a SharePoint
document library.  The workbooks are *not* an API and still contain row-level
quasi-identifiers, so callers must never persist or expose their raw rows.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

SIVIGILA_MICRODATA_DISCOVERY_URL = (
    "https://portalsivigila.ins.gov.co/Microdatos/Forms/AllItems.aspx"
)
SIVIGILA_MICRODATA_FILE_TEMPLATE = (
    "https://portalsivigila.ins.gov.co/Microdatos/Datos_2024_{event_code}.xlsx"
)


class SIVIGILAMicrodataMeasure(StrEnum):
    NOTIFIED_CASE = "notified_case_records"
    IRA_MORBIDITY = "ira_morbidity_attendances"
    IRA_CONTEXT = "ira_irag_context_records"


@dataclass(frozen=True, slots=True)
class SIVIGILA2024EventFile:
    event_code: int
    disease: str
    event_name: str
    measure: SIVIGILAMicrodataMeasure
    canonical_eligible: bool = True

    @property
    def url(self) -> str:
        return SIVIGILA_MICRODATA_FILE_TEMPLATE.format(event_code=self.event_code)


# Direct files verified with HTTP 200 and XLSX media type on 2026-07-13.  Event
# 995 has collective service-attendance counts; it is intentionally not parsed
# as one case per row. Events 345/348 are retained as a sanitised contextual
# layer but are not mixed into the IRA canonical series because their unit and
# sentinel population differ from event 995. Event 348 remains the only IRA
# canonical proxy, matching the historical PRORA contract.
SIVIGILA_2024_EVENT_FILES: dict[int, SIVIGILA2024EventFile] = {
    210: SIVIGILA2024EventFile(210, "dengue", "Dengue", SIVIGILAMicrodataMeasure.NOTIFIED_CASE),
    217: SIVIGILA2024EventFile(
        217,
        "chikunguna",
        "Chikungunya",
        SIVIGILAMicrodataMeasure.NOTIFIED_CASE,
    ),
    220: SIVIGILA2024EventFile(
        220, "dengue", "Dengue grave", SIVIGILAMicrodataMeasure.NOTIFIED_CASE
    ),
    345: SIVIGILA2024EventFile(
        345,
        "ira",
        "ESI-IRAG (vigilancia centinela)",
        SIVIGILAMicrodataMeasure.IRA_CONTEXT,
        canonical_eligible=False,
    ),
    348: SIVIGILA2024EventFile(
        348,
        "ira",
        "IRAG inusitado",
        SIVIGILAMicrodataMeasure.IRA_CONTEXT,
    ),
    420: SIVIGILA2024EventFile(
        420,
        "leishmaniasis",
        "Leishmaniasis cutanea",
        SIVIGILAMicrodataMeasure.NOTIFIED_CASE,
    ),
    430: SIVIGILA2024EventFile(
        430,
        "leishmaniasis",
        "Leishmaniasis mucosa",
        SIVIGILAMicrodataMeasure.NOTIFIED_CASE,
    ),
    440: SIVIGILA2024EventFile(
        440,
        "leishmaniasis",
        "Leishmaniasis visceral",
        SIVIGILAMicrodataMeasure.NOTIFIED_CASE,
    ),
    460: SIVIGILA2024EventFile(
        460,
        "malaria",
        "Malaria asociada (formas mixtas)",
        SIVIGILAMicrodataMeasure.NOTIFIED_CASE,
    ),
    470: SIVIGILA2024EventFile(
        470,
        "malaria",
        "Malaria por Plasmodium falciparum",
        SIVIGILAMicrodataMeasure.NOTIFIED_CASE,
    ),
    490: SIVIGILA2024EventFile(
        490,
        "malaria",
        "Malaria por Plasmodium vivax",
        SIVIGILAMicrodataMeasure.NOTIFIED_CASE,
    ),
    495: SIVIGILA2024EventFile(
        495,
        "malaria",
        "Malaria complicada",
        SIVIGILAMicrodataMeasure.NOTIFIED_CASE,
    ),
    895: SIVIGILA2024EventFile(895, "zika", "Zika", SIVIGILAMicrodataMeasure.NOTIFIED_CASE),
    995: SIVIGILA2024EventFile(
        995,
        "ira",
        "Morbilidad por IRA (notificacion colectiva)",
        SIVIGILAMicrodataMeasure.IRA_MORBIDITY,
        canonical_eligible=False,
    ),
}


def sivigila_2024_event_files(
    requested_codes: list[int] | tuple[int, ...] | None = None,
) -> list[SIVIGILA2024EventFile]:
    if requested_codes is None:
        return list(SIVIGILA_2024_EVENT_FILES.values())
    unknown = sorted(set(requested_codes) - SIVIGILA_2024_EVENT_FILES.keys())
    if unknown:
        raise ValueError(
            "Eventos sin contrato SIVIGILA 2024 aprobado: "
            + ", ".join(str(code) for code in unknown)
        )
    return [SIVIGILA_2024_EVENT_FILES[code] for code in sorted(set(requested_codes))]
