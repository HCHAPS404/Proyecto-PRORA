"""Grounded epidemiological assistant with an optional OpenAI provider.

The service retrieves only aggregated PRORA facts.  It never sends raw patient
records or credentials to the language-model provider.
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any

import httpx
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.epidemiology import (
    DataSource,
    EpidemiologicalObservation,
    Forecast,
    ModelVersion,
    Municipality,
)

SYSTEM_INSTRUCTIONS = """Eres el agente analítico de PRORA, un sistema colombiano de
alerta temprana epidemiológica. Responde en español claro y breve, únicamente con
los hechos agregados proporcionados. Distingue observaciones de predicciones,
incluye incertidumbre, fecha/horizonte y procedencia cuando existan. No diagnostiques,
no reemplaces protocolos oficiales y no inventes cifras. Si faltan datos, dilo.
"""


def _normalise_place(value: str) -> str:
    text = unicodedata.normalize("NFKD", value.casefold())
    return " ".join(
        "".join(character for character in text if not unicodedata.combining(character))
        .replace("-", " ")
        .split()
    )


@dataclass(slots=True)
class AgentSource:
    label: str
    uri: str | None = None
    updated_at: str | None = None

    def as_dict(self) -> dict[str, str | None]:
        return {"label": self.label, "uri": self.uri, "updated_at": self.updated_at}


@dataclass(slots=True)
class AgentResult:
    answer: str
    sources: list[AgentSource] = field(default_factory=list)
    suggested_questions: list[str] = field(default_factory=list)
    provider: str = "deterministic"


class AgentService:
    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str = "gpt-5.4-mini",
        base_url: str = "https://api.openai.com/v1",
        timeout_seconds: float = 30.0,
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    async def answer(
        self,
        session: AsyncSession,
        question: str,
        context: dict[str, Any] | None = None,
    ) -> AgentResult:
        facts, sources = await self._collect_facts(session, question, context or {})
        if self.api_key:
            try:
                text = await self._openai_answer(question, facts)
                return AgentResult(
                    answer=text,
                    sources=sources,
                    suggested_questions=self._suggestions(facts),
                    provider="openai-responses",
                )
            except (httpx.HTTPError, KeyError, ValueError):
                # Availability of the analytical API must not depend on an LLM vendor.
                pass
        return AgentResult(
            answer=self._deterministic_answer(question, facts),
            sources=sources,
            suggested_questions=self._suggestions(facts),
        )

    async def _collect_facts(
        self,
        session: AsyncSession,
        question: str,
        context: dict[str, Any],
    ) -> tuple[dict[str, Any], list[AgentSource]]:
        normalized = question.casefold()
        requested_disease = next(
            (
                disease
                for disease in (
                    "dengue",
                    "malaria",
                    "chikunguna",
                    "zika",
                    "leishmaniasis",
                    "ira",
                )
                if disease in normalized.replace("ñ", "n")
            ),
            str(context.get("disease", "")).casefold() or None,
        )

        requested_territory_code = str(
            context.get("territory_code") or context.get("cod_dane") or ""
        ).strip()
        if not re.fullmatch(r"\d{5}", requested_territory_code):
            code_match = re.search(r"(?<!\d)(\d{5})(?!\d)", question)
            requested_territory_code = code_match.group(1) if code_match else ""
        requested_territory = (
            await session.get(Municipality, requested_territory_code)
            if requested_territory_code
            else None
        )
        if requested_territory is None and not requested_territory_code:
            normalised_question = _normalise_place(question)
            municipality_rows = list((await session.scalars(select(Municipality))).all())
            candidates = [
                municipality
                for municipality in municipality_rows
                if len(_normalise_place(municipality.name)) >= 4
                and re.search(
                    rf"\b{re.escape(_normalise_place(municipality.name))}\b",
                    normalised_question,
                )
            ]
            if candidates:
                # Prefer the longest explicit place name. A department mention
                # disambiguates homonyms; otherwise ambiguity is left unresolved.
                candidates.sort(key=lambda item: len(_normalise_place(item.name)), reverse=True)
                longest = len(_normalise_place(candidates[0].name))
                finalists = [
                    item for item in candidates if len(_normalise_place(item.name)) == longest
                ]
                department_matches = [
                    item
                    for item in finalists
                    if _normalise_place(item.department_name) in normalised_question
                ]
                if len(department_matches) == 1:
                    requested_territory = department_matches[0]
                elif len(finalists) == 1:
                    requested_territory = finalists[0]
        if requested_territory is not None:
            requested_territory_code = requested_territory.code

        observation_filters = []
        if requested_disease:
            observation_filters.append(EpidemiologicalObservation.disease == requested_disease)
        if requested_territory is not None:
            observation_filters.append(
                EpidemiologicalObservation.municipality_code == requested_territory.code
            )
        latest_observation_week = await session.scalar(
            select(func.max(EpidemiologicalObservation.week_start)).where(
                *observation_filters
            )
        )
        latest_observation: dict[str, Any] | None = None
        if latest_observation_week is not None:
            observation_summary = (
                await session.execute(
                    select(
                        func.sum(EpidemiologicalObservation.cases),
                        func.count(func.distinct(EpidemiologicalObservation.municipality_code)),
                        func.avg(EpidemiologicalObservation.quality_score),
                        func.max(EpidemiologicalObservation.is_preliminary),
                    ).where(
                        *observation_filters,
                        EpidemiologicalObservation.week_start == latest_observation_week,
                    )
                )
            ).one()
            observation_source_ids = list(
                (
                    await session.scalars(
                        select(EpidemiologicalObservation.source_id)
                        .where(
                            *observation_filters,
                            EpidemiologicalObservation.week_start == latest_observation_week,
                        )
                        .distinct()
                    )
                ).all()
            )
            latest_observation = {
                "disease": requested_disease,
                "week": latest_observation_week.isoformat(),
                "observed_cases": int(observation_summary[0] or 0),
                "municipalities_with_reports": int(observation_summary[1] or 0),
                "mean_quality_score": (
                    float(observation_summary[2])
                    if observation_summary[2] is not None
                    else None
                ),
                "is_preliminary": bool(observation_summary[3]),
                "source_ids": sorted(
                    source_id for source_id in observation_source_ids if source_id
                ),
                "territory_code": (
                    requested_territory.code if requested_territory is not None else None
                ),
                "municipality": (
                    requested_territory.name if requested_territory is not None else None
                ),
                "department": (
                    requested_territory.department_name
                    if requested_territory is not None
                    else None
                ),
            }

        forecast_stmt = (
            select(Forecast, Municipality)
            .join(Municipality, Municipality.code == Forecast.municipality_code)
            .join(ModelVersion, ModelVersion.id == Forecast.model_version_id)
            .where(
                Forecast.operationally_eligible.is_(True),
                ModelVersion.stage == "champion",
            )
            .order_by(desc(Forecast.issued_at), desc(Forecast.outbreak_probability))
            .limit(12)
        )
        if requested_disease:
            forecast_stmt = forecast_stmt.where(Forecast.disease == requested_disease)
        if requested_territory is not None:
            forecast_stmt = forecast_stmt.where(
                Forecast.municipality_code == requested_territory.code
            )
        forecast_rows = (await session.execute(forecast_stmt)).all()
        withheld_statement = select(func.count(Forecast.id)).where(
            Forecast.operationally_eligible.is_(False)
        )
        if requested_disease:
            withheld_statement = withheld_statement.where(Forecast.disease == requested_disease)
        if requested_territory is not None:
            withheld_statement = withheld_statement.where(
                Forecast.municipality_code == requested_territory.code
            )
        withheld_forecasts = int((await session.scalar(withheld_statement)) or 0)
        forecasts = [
            {
                "municipality_code": forecast.municipality_code,
                "municipality": municipality.name,
                "department": municipality.department_name,
                "disease": forecast.disease,
                "horizon_weeks": forecast.horizon_weeks,
                "target_week": forecast.target_week.isoformat(),
                "predicted_cases": forecast.predicted_cases,
                "interval": [forecast.interval_lower, forecast.interval_upper],
                "outbreak_probability": forecast.outbreak_probability,
                "risk_level": forecast.risk_level,
                "drivers": forecast.drivers[:4],
            }
            for forecast, municipality in forecast_rows
        ]

        model_stmt = select(ModelVersion).order_by(desc(ModelVersion.activated_at)).limit(8)
        if requested_disease:
            model_stmt = model_stmt.where(ModelVersion.disease == requested_disease)
        model_rows = list((await session.scalars(model_stmt)).all())
        models = [
            {
                "disease": item.disease,
                "horizon_weeks": item.horizon_weeks,
                "version": item.version,
                "stage": item.stage,
                "metrics": item.metrics,
                "activated_at": item.activated_at.isoformat() if item.activated_at else None,
            }
            for item in model_rows
        ]

        source_rows = list(
            (
                await session.scalars(
                    select(DataSource).order_by(DataSource.institution, DataSource.name)
                )
            ).all()
        )
        source_facts = [
            {
                "id": source.id,
                "name": source.name,
                "institution": source.institution,
                "status": source.status,
                "last_success_at": source.last_success_at.isoformat()
                if source.last_success_at
                else None,
            }
            for source in source_rows
        ]
        sources = [
            AgentSource(
                label=f"{source.institution} · {source.name}",
                uri=source.endpoint,
                updated_at=(source.last_success_at.isoformat() if source.last_success_at else None),
            )
            for source in source_rows[:6]
        ]
        if latest_observation:
            observation_ids = set(latest_observation["source_ids"])
            for source in reversed(source_rows):
                if source.id in observation_ids and not any(
                    item.uri == source.endpoint for item in sources
                ):
                    sources.insert(
                        0,
                        AgentSource(
                            label=f"{source.institution} · {source.name}",
                            uri=source.endpoint,
                            updated_at=(
                                source.last_success_at.isoformat()
                                if source.last_success_at
                                else None
                            ),
                        ),
                    )
        if forecasts:
            sources.insert(0, AgentSource(label="PRORA · Predicciones registradas"))
        if models:
            sources.insert(0, AgentSource(label="PRORA · Registro de modelos"))
        return {
            "requested_disease": requested_disease,
            "requested_territory": (
                {
                    "code": requested_territory.code,
                    "municipality": requested_territory.name,
                    "department": requested_territory.department_name,
                }
                if requested_territory is not None
                else None
            ),
            "interface_context": context,
            "latest_observation": latest_observation,
            "forecasts": forecasts,
            "withheld_forecasts": withheld_forecasts,
            "models": models,
            "data_sources": source_facts,
        }, sources

    async def _openai_answer(self, question: str, facts: dict[str, Any]) -> str:
        payload = {
            "model": self.model,
            "instructions": SYSTEM_INSTRUCTIONS,
            "input": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": (
                                f"Pregunta: {question}\n\nContexto PRORA verificado:\n"
                                + json.dumps(facts, ensure_ascii=False, default=str)
                            ),
                        }
                    ],
                }
            ],
        }
        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            response = await client.post(
                f"{self.base_url}/responses",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            response.raise_for_status()
            body = response.json()
        if isinstance(body.get("output_text"), str) and body["output_text"].strip():
            return body["output_text"].strip()
        for item in body.get("output", []):
            for content in item.get("content", []):
                if content.get("type") == "output_text" and content.get("text"):
                    return str(content["text"]).strip()
        raise ValueError("The Responses API did not return text")

    @staticmethod
    def _deterministic_answer(question: str, facts: dict[str, Any]) -> str:
        observation = facts.get("latest_observation")
        forecasts = facts["forecasts"]
        models = facts["models"]
        sources = facts["data_sources"]
        normalized = question.casefold()
        asks_observation = any(
            token in normalized
            for token in ("corte", "históric", "observad", "últim", "ultima", "casos")
        )
        asks_forecast = any(
            token in normalized
            for token in ("predic", "pronóst", "riesgo", "alerta", "proyecci")
        )
        asks_sources = any(
            token in normalized for token in ("fuente", "dataset", "dato", "api", "origen")
        )
        if observation and asks_observation and not asks_forecast:
            disease_label = observation["disease"] or "los eventos disponibles"
            place_label = (
                f" en {observation['municipality']}, {observation['department']}"
                if observation.get("municipality")
                else ""
            )
            source_label = ", ".join(observation["source_ids"]) or "fuentes registradas"
            observed_cases = f"{observation['observed_cases']:,}".replace(",", ".")
            preliminary = (
                " El corte está marcado como preliminar."
                if observation["is_preliminary"]
                else ""
            )
            territory_scope = (
                "en el territorio seleccionado. "
                if observation.get("territory_code")
                else (
                    f"en {observation['municipalities_with_reports']} municipios "
                    "con notificación. "
                )
            )
            return (
                f"El último corte observado para {disease_label}{place_label} es la semana del "
                f"{observation['week']}: {observed_cases} casos agregados "
                f"{territory_scope}"
                f"Es una observación histórica, no una predicción actual, y procede de "
                f"{source_label}.{preliminary}"
            )
        if asks_sources and sources:
            active_sources = [source for source in sources if source["status"] == "active"]
            with_data = [source for source in active_sources if source["last_success_at"]]
            names = ", ".join(
                f"{source['institution']} ({source['name']})" for source in with_data[:5]
            )
            remainder = max(0, len(with_data) - 5)
            suffix = f" y {remainder} más" if remainder else ""
            return (
                f"PRORA tiene {len(active_sources)} de {len(sources)} fuentes activas; "
                f"{len(with_data)} ya registran una sincronización exitosa. "
                f"Entre ellas: {names}{suffix}. Consulte el inventario para corte, filas, "
                "calidad y SHA-256 de cada snapshot."
            )
        if forecasts:
            highest = max(forecasts, key=lambda item: item["outbreak_probability"])
            interval = highest["interval"]
            lead = (
                f"La señal registrada de mayor prioridad es {highest['disease']} en "
                f"{highest['municipality']}, {highest['department']}: "
                f"{highest['outbreak_probability']:.0%} de probabilidad a "
                f"{highest['horizon_weeks']} semanas. El modelo estima "
                f"{highest['predicted_cases']:.0f} casos, con intervalo "
                f"{interval[0]:.0f}–{interval[1]:.0f}."
            )
            if "modelo" in normalized and models:
                model = models[0]
                return lead + f" Se calculó con {model['version']} y métricas {model['metrics']}."
            return lead + " Debe contrastarse con vigilancia territorial antes de actuar."
        if models:
            model = models[0]
            withheld = int(facts.get("withheld_forecasts", 0))
            withheld_notice = (
                f" Se retuvieron {withheld} pronósticos por antigüedad del dato y no se "
                "publican como riesgo actual."
                if withheld
                else ""
            )
            return (
                f"El registro contiene el modelo {model['version']} para "
                f"{model['disease']} a {model['horizon_weeks']} semanas, en etapa "
                f"{model['stage']}.{withheld_notice} Puede consultar su traza para ver "
                "dataset, hashes, validación e intervalos."
            )
        if sources:
            available = sum(source["status"] == "active" for source in sources)
            withheld = int(facts.get("withheld_forecasts", 0))
            stale_notice = (
                f" Hay {withheld} pronósticos históricos retenidos por datos obsoletos; "
                "no se presentan como riesgo actual."
                if withheld
                else ""
            )
            return (
                f"PRORA tiene {available} de {len(sources)} fuentes configuradas como activas, "
                "pero aún no hay predicciones persistidas para responder con una cifra. "
                "Ejecute la sincronización y el entrenamiento del modelo solicitado."
                + stale_notice
            )
        return (
            "El backend está operativo, pero todavía no contiene fuentes sincronizadas ni "
            "predicciones registradas. Configure las fuentes oficiales, ejecute la ingestión "
            "y entrene los modelos antes de solicitar una interpretación cuantitativa."
        )

    @staticmethod
    def _suggestions(facts: dict[str, Any]) -> list[str]:
        if facts["forecasts"]:
            return [
                "¿Qué municipios tienen riesgo crítico?",
                "¿Qué variables impulsan la alerta principal?",
                "¿Qué incertidumbre tiene la predicción?",
            ]
        return [
            "¿Cuál es el último corte observado de dengue?",
            "¿Qué fuentes tienen datos almacenados?",
            "¿Hay modelos registrados pero retenidos por antigüedad?",
        ]
