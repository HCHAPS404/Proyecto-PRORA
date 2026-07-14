"""Auditable data and model readiness for every prioritized disease."""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

import pandas as pd
from sqlalchemy import case, desc, distinct, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.epidemiology import (
    ClimateObservation,
    DeforestationObservation,
    EpidemiologicalObservation,
    ModelTrainingRun,
    ModelVersion,
    Municipality,
    SocioeconomicIndicator,
    VaccinationCoverage,
)

from .config import MLConfig


def assess_training_frame(
    frame: pd.DataFrame,
    disease: str,
    config: MLConfig | None = None,
) -> dict[str, Any]:
    """Assess research and operational suitability without inventing reports.

    A missing municipality/week is not interpreted as zero. Operational use is
    therefore withheld when the source contains no explicit zero-case reports,
    even when there are enough positive observations for a research model.
    """

    cfg = config or MLConfig()
    cases = pd.to_numeric(frame.get("cases", pd.Series(dtype=float)), errors="coerce")
    observed = cases.notna()
    observed_rows = int(observed.sum())
    calendar_rows = int(len(frame))
    zero_rows = int((cases[observed] == 0).sum())
    territories = int(frame["territory_id"].nunique()) if "territory_id" in frame else 0
    unique_weeks = int(frame["week"].nunique()) if "week" in frame else 0
    cutoff = pd.to_datetime(frame["week"], errors="coerce").max() if len(frame) else pd.NaT
    observation_age_days = (date.today() - cutoff.date()).days if pd.notna(cutoff) else None
    reporting_density = observed_rows / calendar_rows if calendar_rows else 0.0

    requirements = {
        "observed_rows": {
            "actual": observed_rows,
            "minimum": cfg.min_observed_training_rows,
            "passes": observed_rows >= cfg.min_observed_training_rows,
        },
        "territories": {
            "actual": territories,
            "minimum": cfg.min_training_territories,
            "passes": territories >= cfg.min_training_territories,
        },
        "unique_weeks": {
            "actual": unique_weeks,
            "minimum": cfg.min_training_weeks,
            "passes": unique_weeks >= cfg.min_training_weeks,
        },
        "reporting_density": {
            "actual": round(reporting_density, 6),
            "minimum": cfg.min_reporting_density,
            "passes": reporting_density >= cfg.min_reporting_density,
        },
    }
    # Sparse surveillance events may still support a strictly retrospective,
    # research-only benchmark when volume, territorial breadth and temporal
    # span are sufficient. Reporting density remains an operational gate: an
    # absent municipality/week is never converted to a zero-case report.
    research_core = all(
        requirements[key]["passes"]
        for key in ("observed_rows", "territories", "unique_weeks")
    )
    explicit_zero_evidence = zero_rows > 0
    fresh = (
        observation_age_days is not None and observation_age_days <= cfg.max_forecast_data_age_days
    )
    near_complete_panel = reporting_density >= 0.95
    outcome_complete_enough = requirements["reporting_density"]["passes"] and (
        explicit_zero_evidence or near_complete_panel
    )
    operational = research_core and outcome_complete_enough and fresh

    limitations: list[dict[str, str]] = []
    if not explicit_zero_evidence and not near_complete_panel:
        limitations.append(
            {
                "code": "no_explicit_zero_case_reports",
                "severity": "blocking",
                "message": (
                    "La fuente contiene solo filas con casos positivos y un panel incompleto; "
                    "las semanas ausentes siguen como NaN y no permiten estimar riesgo de "
                    "cero casos."
                ),
            }
        )
    if not requirements["reporting_density"]["passes"]:
        limitations.append(
            {
                "code": "low_reporting_density",
                "severity": "blocking",
                "message": "La densidad de semanas reportadas es insuficiente para uso operativo.",
            }
        )
    if not fresh:
        limitations.append(
            {
                "code": "stale_epidemiological_cutoff",
                "severity": "blocking",
                "message": "El corte epidemiologico supera la edad maxima operativa.",
            }
        )
    for key, item in requirements.items():
        if key != "reporting_density" and not item["passes"]:
            limitations.append(
                {
                    "code": f"insufficient_{key}",
                    "severity": "blocking",
                    "message": f"No se cumple el minimo de {key} para entrenar.",
                }
            )

    return {
        "disease": disease,
        "research_training_eligible": research_core,
        "readiness_level": (
            "operational" if operational else "research_only" if research_core else "insufficient"
        ),
        "operational_forecast_eligible": operational,
        "outcome_reporting_complete_enough": outcome_complete_enough,
        "explicit_zero_case_rows": zero_rows,
        "observed_case_rows": observed_rows,
        "calendar_rows": calendar_rows,
        "missing_case_weeks": calendar_rows - observed_rows,
        "reporting_density": round(reporting_density, 6),
        "territories": territories,
        "unique_weeks": unique_weeks,
        "week_start": _date_value(frame["week"].min()) if len(frame) else None,
        "week_end": _date_value(cutoff) if pd.notna(cutoff) else None,
        "observation_age_days": observation_age_days,
        "requirements": requirements,
        "limitations": limitations,
        "missing_week_policy": "NaN; never inferred as zero",
    }


async def build_model_portfolio_readiness(
    session: AsyncSession,
    config: MLConfig | None = None,
) -> dict[str, Any]:
    """Return a cheap DB-backed portfolio audit for the public API."""

    cfg = config or MLConfig()
    grouped = (
        await session.execute(
            select(
                EpidemiologicalObservation.disease,
                EpidemiologicalObservation.municipality_code,
                func.count(EpidemiologicalObservation.id),
                func.min(EpidemiologicalObservation.week_start),
                func.max(EpidemiologicalObservation.week_start),
                func.sum(EpidemiologicalObservation.cases),
                func.sum(case((EpidemiologicalObservation.cases == 0, 1), else_=0)),
            ).group_by(
                EpidemiologicalObservation.disease,
                EpidemiologicalObservation.municipality_code,
            )
        )
    ).all()
    week_counts = {
        str(disease): int(count or 0)
        for disease, count in (
            await session.execute(
                select(
                    EpidemiologicalObservation.disease,
                    func.count(distinct(EpidemiologicalObservation.week_start)),
                ).group_by(EpidemiologicalObservation.disease)
            )
        ).all()
    }
    by_disease: dict[str, list[Any]] = {disease: [] for disease in cfg.diseases}
    for row in grouped:
        by_disease.setdefault(str(row[0]), []).append(row)

    champions = list(
        (
            await session.scalars(
                select(ModelVersion)
                .where(ModelVersion.stage == "champion")
                .order_by(ModelVersion.disease, ModelVersion.horizon_weeks)
            )
        ).all()
    )
    models_by_disease: dict[str, dict[int, ModelVersion]] = {}
    for model in champions:
        models_by_disease.setdefault(model.disease, {})[model.horizon_weeks] = model

    jobs = list(
        (
            await session.scalars(
                select(ModelTrainingRun).order_by(desc(ModelTrainingRun.created_at))
            )
        ).all()
    )
    latest_jobs: dict[str, ModelTrainingRun] = {}
    for job in jobs:
        latest_jobs.setdefault(job.disease, job)

    diseases: list[dict[str, Any]] = []
    for disease in cfg.diseases:
        rows = by_disease.get(disease, [])
        observed_rows = sum(int(row[2] or 0) for row in rows)
        calendar_rows = sum(
            ((row[4] - row[3]).days // 7) + 1
            for row in rows
            if row[3] is not None and row[4] is not None
        )
        zero_rows = sum(int(row[6] or 0) for row in rows)
        start = min((row[3] for row in rows if row[3] is not None), default=None)
        end = max((row[4] for row in rows if row[4] is not None), default=None)
        density = observed_rows / calendar_rows if calendar_rows else 0.0
        age = (date.today() - end).days if end else None
        requirement_passes = {
            "observed_rows": observed_rows >= cfg.min_observed_training_rows,
            "territories": len(rows) >= cfg.min_training_territories,
            "unique_weeks": week_counts.get(disease, 0) >= cfg.min_training_weeks,
            "reporting_density": density >= cfg.min_reporting_density,
        }
        research_eligible = all(
            requirement_passes[key]
            for key in ("observed_rows", "territories", "unique_weeks")
        )
        outcome_complete = requirement_passes["reporting_density"] and (
            zero_rows > 0 or density >= 0.95
        )
        operational = bool(
            research_eligible
            and outcome_complete
            and age is not None
            and age <= cfg.max_forecast_data_age_days
        )
        horizon_models = models_by_disease.get(disease, {})
        model_rows = []
        for horizon in cfg.horizons:
            model = horizon_models.get(horizon)
            metrics = model.metrics if model else {}
            model_rows.append(
                {
                    "horizon": horizon,
                    "state": "trained" if model else "not_trained",
                    "version": model.version if model else None,
                    "stage": model.stage if model else None,
                    "training_period": (
                        {
                            "from": model.training_started_on,
                            "to": model.training_ended_on,
                        }
                        if model
                        else None
                    ),
                    "validation": (
                        {
                            "temporal_mae": metrics.get("mae"),
                            "temporal_auc": metrics.get("auc"),
                            "territorial_mae": metrics.get("territorial_mae"),
                            "territorial_auc": metrics.get("territorial_auc"),
                            "conformal_coverage": metrics.get("conformal_oof_empirical_coverage"),
                            "benchmark_available": bool(metrics.get("benchmark")),
                        }
                        if model
                        else {}
                    ),
                }
            )
        latest_job = latest_jobs.get(disease)
        limitations = []
        if not rows:
            limitations.append("no_epidemiological_observations")
        if zero_rows == 0 and density < 0.95 and rows:
            limitations.append("no_explicit_zero_case_reports")
        if not requirement_passes["reporting_density"] and rows:
            limitations.append("low_reporting_density")
        if age is None or age > cfg.max_forecast_data_age_days:
            limitations.append("stale_or_missing_epidemiological_cutoff")
        if len(horizon_models) < len(cfg.horizons):
            limitations.append("missing_trained_horizons")
        diseases.append(
            {
                "disease": disease,
                "data": {
                    "observed_rows": observed_rows,
                    "calendar_rows": calendar_rows,
                    "reporting_density": round(density, 6),
                    "explicit_zero_case_rows": zero_rows,
                    "territories": len(rows),
                    "unique_weeks": week_counts.get(disease, 0),
                    "week_start": start,
                    "week_end": end,
                    "observation_age_days": age,
                    "total_cases": sum(int(row[5] or 0) for row in rows),
                },
                "research_training_eligible": research_eligible,
                "operational_forecast_eligible": operational,
                "readiness_level": (
                    "operational"
                    if operational
                    else "research_only"
                    if research_eligible
                    else "insufficient"
                ),
                "requirements": requirement_passes,
                "models": model_rows,
                "latest_training_job": (
                    {
                        "job_id": latest_job.id,
                        "status": latest_job.status,
                        "created_at": latest_job.created_at,
                        "finished_at": latest_job.finished_at,
                        "error_message": latest_job.error_message,
                    }
                    if latest_job
                    else None
                ),
                "limitations": limitations,
            }
        )

    return {
        "generated_at": datetime.now(UTC),
        "policy": {
            "missing_week_policy": "NaN; never inferred as zero",
            "research_minimums": {
                "observed_rows": cfg.min_observed_training_rows,
                "territories": cfg.min_training_territories,
                "unique_weeks": cfg.min_training_weeks,
            },
            "operational_requirements": {
                "maximum_data_age_days": cfg.max_forecast_data_age_days,
                "minimum_reporting_density": cfg.min_reporting_density,
                "outcome_completeness": (
                    "explicit zero-case reports or at least 95% calendar coverage"
                ),
                "champions_required_for_horizons": list(cfg.horizons),
            },
        },
        "diseases": diseases,
        "covariate_inventory": await _covariate_inventory(session),
    }


async def _covariate_inventory(session: AsyncSession) -> dict[str, Any]:
    municipality_count = int((await session.scalar(select(func.count(Municipality.code)))) or 0)
    climate = (
        await session.execute(
            select(
                func.count(ClimateObservation.id),
                func.count(distinct(ClimateObservation.municipality_code)),
                func.min(ClimateObservation.week_start),
                func.max(ClimateObservation.week_start),
                func.sum(case((ClimateObservation.precipitation_mm.is_not(None), 1), else_=0)),
                func.sum(case((ClimateObservation.temperature_mean_c.is_not(None), 1), else_=0)),
                func.sum(case((ClimateObservation.humidity_relative_pct.is_not(None), 1), else_=0)),
                func.count(distinct(ClimateObservation.week_start)),
            )
        )
    ).one()
    climate_span_weeks = (
        ((climate[3] - climate[2]).days // 7) + 1
        if climate[2] is not None and climate[3] is not None
        else 0
    )
    climate_territory_coverage = (
        float(climate[1] or 0) / municipality_count if municipality_count else 0.0
    )
    climate_week_coverage = (
        float(climate[7] or 0) / climate_span_weeks if climate_span_weeks else 0.0
    )
    climate_status = (
        "unavailable"
        if not climate[0]
        else "available"
        if climate_territory_coverage >= 0.95 and climate_week_coverage >= 0.95
        else "partial"
    )
    vaccination = (
        await session.execute(
            select(
                func.count(VaccinationCoverage.id),
                func.count(distinct(VaccinationCoverage.municipality_code)),
                func.min(VaccinationCoverage.year),
                func.max(VaccinationCoverage.year),
                func.count(distinct(VaccinationCoverage.vaccine)),
            )
        )
    ).one()
    deforestation = (
        await session.execute(
            select(
                func.count(DeforestationObservation.id),
                func.count(distinct(DeforestationObservation.municipality_code)),
                func.min(DeforestationObservation.year),
                func.max(DeforestationObservation.year),
            )
        )
    ).one()
    socioeconomic = (
        await session.execute(
            select(
                func.count(SocioeconomicIndicator.id),
                func.count(distinct(SocioeconomicIndicator.municipality_code)),
                func.min(SocioeconomicIndicator.year),
                func.max(SocioeconomicIndicator.year),
                func.sum(case((SocioeconomicIndicator.water_access_pct.is_not(None), 1), else_=0)),
                func.sum(case((SocioeconomicIndicator.sewer_access_pct.is_not(None), 1), else_=0)),
                func.sum(case((SocioeconomicIndicator.overcrowding_pct.is_not(None), 1), else_=0)),
                func.sum(case((SocioeconomicIndicator.nbi_pct.is_not(None), 1), else_=0)),
                func.sum(
                    case((SocioeconomicIndicator.urban_population_pct.is_not(None), 1), else_=0)
                ),
                func.sum(
                    case((SocioeconomicIndicator.rural_population_pct.is_not(None), 1), else_=0)
                ),
            )
        )
    ).one()
    return {
        "climate": {
            "rows": int(climate[0] or 0),
            "territories": int(climate[1] or 0),
            "from": climate[2],
            "to": climate[3],
            "precipitation_rows": int(climate[4] or 0),
            "temperature_rows": int(climate[5] or 0),
            "humidity_rows": int(climate[6] or 0),
            "unique_weeks": int(climate[7] or 0),
            "calendar_weeks_in_span": climate_span_weeks,
            "territory_coverage_pct": round(climate_territory_coverage * 100, 3),
            "week_coverage_pct": round(climate_week_coverage * 100, 3),
            "status": climate_status,
        },
        "pai_municipal": {
            "rows": int(vaccination[0] or 0),
            "territories": int(vaccination[1] or 0),
            "from_year": vaccination[2],
            "to_year": vaccination[3],
            "series": int(vaccination[4] or 0),
            "status": "available" if vaccination[0] else "unavailable",
            "interpretation": "health-system/access proxy; not causal protection",
        },
        "deforestation": {
            "rows": int(deforestation[0] or 0),
            "territories": int(deforestation[1] or 0),
            "from_year": deforestation[2],
            "to_year": deforestation[3],
            "status": "available" if deforestation[0] else "unavailable",
        },
        "socioeconomic": {
            "rows": int(socioeconomic[0] or 0),
            "territories": int(socioeconomic[1] or 0),
            "from_year": socioeconomic[2],
            "to_year": socioeconomic[3],
            "water_rows": int(socioeconomic[4] or 0),
            "sewer_rows": int(socioeconomic[5] or 0),
            "overcrowding_rows": int(socioeconomic[6] or 0),
            "nbi_rows": int(socioeconomic[7] or 0),
            "status": "partial" if socioeconomic[0] else "unavailable",
        },
        "urban_rural": {
            "rows": int(min(int(socioeconomic[8] or 0), int(socioeconomic[9] or 0))),
            "urban_rows": int(socioeconomic[8] or 0),
            "rural_rows": int(socioeconomic[9] or 0),
            "territories": int(min(int(socioeconomic[8] or 0), int(socioeconomic[9] or 0))),
            "status": ("available" if socioeconomic[8] and socioeconomic[9] else "unavailable"),
            "source": "DANE CNPV 2018 class composition, layer 801",
        },
    }


def _date_value(value: Any) -> str | None:
    if value is None or pd.isna(value):
        return None
    return pd.Timestamp(value).date().isoformat()
