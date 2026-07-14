"""Evidence-backed coverage report for the six PRORA disease domains."""

from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import case, distinct, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.epidemiology import (
    AlertEvent,
    EpidemiologicalObservation,
    Forecast,
    ModelVersion,
)
from app.schemas.sources import DiseaseDataCoverage

PRIORITIZED_DISEASES = (
    "dengue",
    "malaria",
    "chikunguna",
    "zika",
    "leishmaniasis",
    "ira",
)
CURRENT_DATA_MAX_AGE_DAYS = 35


async def disease_data_coverage(session: AsyncSession) -> list[DiseaseDataCoverage]:
    """Return availability without promoting historical rows to live signals."""

    today = date.today()
    current_cutoff = today - timedelta(days=CURRENT_DATA_MAX_AGE_DAYS)
    result: list[DiseaseDataCoverage] = []

    for disease in PRIORITIZED_DISEASES:
        observation = (
            await session.execute(
                select(
                    func.count(EpidemiologicalObservation.id),
                    func.coalesce(func.sum(EpidemiologicalObservation.cases), 0),
                    func.count(distinct(EpidemiologicalObservation.municipality_code)),
                    func.min(EpidemiologicalObservation.week_start),
                    func.max(EpidemiologicalObservation.week_start),
                ).where(EpidemiologicalObservation.disease == disease)
            )
        ).one()
        rows = int(observation[0] or 0)
        observed_cases = int(observation[1] or 0)
        municipalities = int(observation[2] or 0)
        period_start = observation[3]
        period_end = observation[4]
        age_days = (today - period_end).days if period_end else None
        source_ids = sorted(
            set(
                await session.scalars(
                    select(EpidemiologicalObservation.source_id)
                    .where(EpidemiologicalObservation.disease == disease)
                    .distinct()
                )
            )
        )
        horizons = sorted(
            set(
                await session.scalars(
                    select(ModelVersion.horizon_weeks)
                    .where(
                        ModelVersion.disease == disease,
                        ModelVersion.stage == "champion",
                    )
                    .distinct()
                )
            )
        )
        forecasts = (
            await session.execute(
                select(
                    func.coalesce(
                        func.sum(
                            case(
                                (
                                    (Forecast.operationally_eligible.is_(False))
                                    | (Forecast.target_week < today),
                                    1,
                                ),
                                else_=0,
                            )
                        ),
                        0,
                    ),
                    func.coalesce(
                        func.sum(
                            case(
                                (
                                    (Forecast.operationally_eligible.is_(True))
                                    & (Forecast.target_week >= today),
                                    1,
                                ),
                                else_=0,
                            )
                        ),
                        0,
                    ),
                )
                .join(ModelVersion, ModelVersion.id == Forecast.model_version_id)
                .where(
                    Forecast.disease == disease,
                    ModelVersion.stage == "champion",
                )
            )
        ).one()
        historical_forecasts = int(forecasts[0] or 0)
        operational_forecasts = int(forecasts[1] or 0)
        open_alerts = int(
            await session.scalar(
                select(func.count(AlertEvent.id))
                .join(Forecast, Forecast.id == AlertEvent.forecast_id)
                .join(ModelVersion, ModelVersion.id == Forecast.model_version_id)
                .where(
                    Forecast.disease == disease,
                    Forecast.operationally_eligible.is_(True),
                    Forecast.target_week >= today,
                    ModelVersion.stage == "champion",
                    AlertEvent.status.in_(("open", "active")),
                )
            )
            or 0
        )

        if period_end is None:
            observation_status = "no_data"
        elif period_end >= current_cutoff:
            observation_status = "current"
        else:
            observation_status = "historical"

        blocking_reasons = []
        if not rows:
            blocking_reasons.append("no_observations")
        elif observation_status == "historical":
            blocking_reasons.append("epidemiological_cutoff_is_historical")
        if not horizons:
            blocking_reasons.append("no_champion_model")
        if not operational_forecasts:
            blocking_reasons.append("no_operational_forecasts")

        result.append(
            DiseaseDataCoverage(
                disease=disease,
                observation_status=observation_status,
                observation_rows=rows,
                observed_cases=observed_cases,
                municipalities_with_observations=municipalities,
                period_start=period_start,
                period_end=period_end,
                observation_age_days=age_days,
                source_ids=source_ids,
                champion_model_horizons=horizons,
                historical_forecasts=historical_forecasts,
                operational_forecasts=operational_forecasts,
                open_operational_alerts=open_alerts,
                operational_ready=(
                    observation_status == "current"
                    and bool(horizons)
                    and operational_forecasts > 0
                ),
                blocking_reasons=blocking_reasons,
            )
        )
    return result
