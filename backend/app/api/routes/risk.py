from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy import Integer, and_, cast, desc, func, or_, select

from app.api.dependencies import SessionDep, get_runtime_settings, require_roles
from app.core.config import Settings
from app.core.errors import DomainError
from app.ml.concurrency import acquire_model_promotion_locks
from app.ml.readiness import build_model_portfolio_readiness
from app.ml.registry import ModelRegistry
from app.models.entities import User, UserRole
from app.models.epidemiology import (
    AlertEvent,
    DataSource,
    EpidemiologicalBulletinAggregate,
    EpidemiologicalObservation,
    Forecast,
    ModelTrainingRun,
    ModelVersion,
    Municipality,
)
from app.schemas.risk import (
    AlertEventResponse,
    AlertReviewRequest,
    AnalyticsForecastPoint,
    AnalyticsForecastSeriesResponse,
    AnalyticsSeriesPoint,
    AnalyticsSeriesResponse,
    AnalyticsSummaryResponse,
    AnalyticsWindowAggregate,
    CurrentOfficialReferenceResponse,
    Disease,
    ExplanationResponse,
    HistoricalPointResponse,
    HistoricalTerritoriesResponse,
    HistoricalTerritoryItemResponse,
    ModelActivationResponse,
    ModelMetadataResponse,
    ModelPortfolioReadinessResponse,
    ModelTraceResponse,
    ModelVersionSummary,
    ProvenanceSourceResponse,
    RiskMapItem,
    TrainingJobResponse,
    TrainingRequest,
)

router = APIRouter(tags=["risk and models"])
Operator = Annotated[User, Depends(require_roles(UserRole.ANALYST, UserRole.ADMIN))]
RISK_TRANSLATION = {"low": "bajo", "moderate": "moderado", "high": "alto", "critical": "critico"}


def _forecast_mode(forecast: Forecast) -> str:
    eligible = bool(getattr(forecast, "operationally_eligible", True))
    if eligible and forecast.target_week >= date.today():
        return "operational"
    return "retrospective_research"


def _risk_item(
    forecast: Forecast, municipality: Municipality, version: ModelVersion
) -> RiskMapItem:
    level = RISK_TRANSLATION.get(forecast.risk_level, forecast.risk_level)
    mode = _forecast_mode(forecast)
    return RiskMapItem(
        cod_dane=municipality.code,
        municipality=municipality.name,
        department=municipality.department_name,
        disease=forecast.disease,
        horizon=forecast.horizon_weeks,
        risk_score=round(forecast.outbreak_probability * 100, 2),
        risk_level=level,
        expected_cases=forecast.predicted_cases,
        lower_bound=forecast.interval_lower,
        upper_bound=forecast.interval_upper,
        population=municipality.population,
        latitude=municipality.latitude,
        longitude=municipality.longitude,
        target_week=forecast.target_week,
        updated_at=forecast.issued_at,
        model_version=version.version,
        data_completeness=forecast.data_completeness,
        observation_cutoff=getattr(forecast, "observation_cutoff", None),
        observation_age_days=getattr(forecast, "observation_age_days", None),
        operationally_eligible=mode == "operational",
        forecast_mode=mode,  # type: ignore[arg-type]
    )


def _operational_forecast_filter():
    if hasattr(Forecast, "operationally_eligible"):
        return and_(
            Forecast.operationally_eligible.is_(True),
            Forecast.target_week >= date.today(),
        )
    return Forecast.target_week >= date.today()


def _champion_forecast_clause(*, operational_only: bool):
    clauses = [ModelVersion.stage == "champion"]
    if operational_only:
        clauses.append(_operational_forecast_filter())
    return and_(*clauses)


def _territory_scope(territory: str):
    normalized = territory.strip().lower()
    if normalized == "national":
        return "national", "national", None
    if normalized.isdigit() and len(normalized) == 2:
        return normalized, "department", Municipality.department_code == normalized
    if normalized.isdigit() and len(normalized) == 5:
        return normalized, "municipality", Municipality.code == normalized
    raise DomainError(
        "invalid_territory",
        "Use 'national', un codigo departamental de 2 digitos o DIVIPOLA de 5 digitos",
        422,
    )


async def _observed_series(
    session: SessionDep,
    territory: str,
    disease: Disease,
    date_from: date | None = None,
    date_to: date | None = None,
) -> tuple[str, str, list[AnalyticsSeriesPoint], dict]:
    normalized, scope, territory_filter = _territory_scope(territory)
    population_statement = select(
        func.sum(Municipality.population),
        func.count(Municipality.code),
        func.count(Municipality.population),
    )
    vintage_statement = select(Municipality.source_vintage).distinct()
    if territory_filter is not None:
        population_statement = population_statement.where(territory_filter)
        vintage_statement = vintage_statement.where(territory_filter)
    population, scope_municipalities, known_population_municipalities = (
        await session.execute(population_statement)
    ).one()
    vintages = sorted(
        str(value)
        for value in (await session.scalars(vintage_statement)).all()
        if value is not None
    )
    population_value = int(population) if population else None
    denominator_metadata = {
        "population": population_value,
        "scope_municipalities": int(scope_municipalities or 0),
        "municipalities_with_population": int(known_population_municipalities or 0),
        "source_vintages": vintages,
        "policy": "full municipality registry scope; independent of case notification rows",
    }
    statement = (
        select(
            EpidemiologicalObservation.week_start,
            func.sum(EpidemiologicalObservation.cases),
            func.avg(EpidemiologicalObservation.quality_score),
            func.max(cast(EpidemiologicalObservation.is_preliminary, Integer)),
            func.count(func.distinct(EpidemiologicalObservation.municipality_code)),
        )
        .join(Municipality, Municipality.code == EpidemiologicalObservation.municipality_code)
        .where(EpidemiologicalObservation.disease == disease)
        .group_by(EpidemiologicalObservation.week_start)
        .order_by(EpidemiologicalObservation.week_start)
    )
    if territory_filter is not None:
        statement = statement.where(territory_filter)
    if date_from is not None:
        statement = statement.where(EpidemiologicalObservation.week_start >= date_from)
    if date_to is not None:
        statement = statement.where(EpidemiologicalObservation.week_start <= date_to)
    rows = (await session.execute(statement)).all()
    points = []
    for week, cases, quality, preliminary, municipality_count in rows:
        observed = int(cases or 0)
        points.append(
            AnalyticsSeriesPoint(
                week=week,
                observed_cases=observed,
                population=population_value,
                incidence_per_100k=(
                    round(observed * 100_000 / population_value, 4) if population_value else None
                ),
                mean_quality_score=round(float(quality), 4) if quality is not None else None,
                is_preliminary=bool(preliminary),
                municipalities_with_notified_cases=int(municipality_count or 0),
            )
        )
    return normalized, scope, points, denominator_metadata


def _observed_window(
    points: list[AnalyticsSeriesPoint],
    *,
    latest_week: date,
    weeks: int,
    population: int | None,
) -> AnalyticsWindowAggregate:
    """Aggregate published observations without treating missing weeks as zero."""

    current_from = latest_week - timedelta(weeks=weeks - 1)
    current = [point for point in points if current_from <= point.week <= latest_week]
    previous_to = current_from - timedelta(weeks=1)
    previous_from = previous_to - timedelta(weeks=weeks - 1)
    previous = [point for point in points if previous_from <= point.week <= previous_to]
    observed_cases = sum(point.observed_cases for point in current)
    previous_cases = sum(point.observed_cases for point in previous) if previous else None
    comparable = len(current) == weeks and len(previous) == weeks
    percent_change = (
        round((observed_cases - previous_cases) * 100 / previous_cases, 4)
        if comparable and previous_cases
        else None
    )
    return AnalyticsWindowAggregate(
        weeks=weeks,
        from_week=current_from,
        to_week=latest_week,
        observed_cases=observed_cases,
        observed_week_count=len(current),
        missing_week_count=max(0, weeks - len(current)),
        previous_observed_cases=previous_cases,
        previous_observed_week_count=len(previous),
        previous_missing_week_count=max(0, weeks - len(previous)),
        comparable=comparable,
        percent_change_vs_previous=percent_change,
        incidence_per_100k=(
            round(observed_cases * 100_000 / population, 4) if population else None
        ),
    )


@router.get("/analytics/summary", response_model=AnalyticsSummaryResponse)
async def analytics_summary(
    session: SessionDep,
    disease: Disease,
    territory: str = Query(default="national", min_length=2, max_length=12),
) -> AnalyticsSummaryResponse:
    normalized, scope, all_points, denominator = await _observed_series(session, territory, disease)
    points = all_points[-2:]
    latest = points[-1] if points else None
    previous = points[-2] if len(points) > 1 else None
    comparison_gap_days = (latest.week - previous.week).days if latest and previous else None
    comparison_comparable = comparison_gap_days == 7
    absolute_change = (
        latest.observed_cases - previous.observed_cases if latest and previous else None
    )
    percent_change = (
        round(absolute_change * 100 / previous.observed_cases, 4)
        if (
            comparison_comparable
            and absolute_change is not None
            and previous
            and previous.observed_cases
        )
        else None
    )
    age_days = (date.today() - latest.week).days if latest else None
    source_items: list[ProvenanceSourceResponse] = []
    if latest:
        _, _, territory_filter = _territory_scope(territory)
        source_statement = (
            select(DataSource)
            .join(
                EpidemiologicalObservation,
                EpidemiologicalObservation.source_id == DataSource.id,
            )
            .join(Municipality, Municipality.code == EpidemiologicalObservation.municipality_code)
            .where(
                EpidemiologicalObservation.disease == disease,
                EpidemiologicalObservation.week_start == latest.week,
            )
            .distinct()
        )
        if territory_filter is not None:
            source_statement = source_statement.where(territory_filter)
        sources = list((await session.scalars(source_statement)).all())
        source_items = [
            ProvenanceSourceResponse(
                source_id=source.id,
                name=source.name,
                institution=source.institution,
                last_success_at=source.last_success_at,
            )
            for source in sources
        ]
    return AnalyticsSummaryResponse(
        territory=normalized,
        scope=scope,
        disease=disease,
        latest=latest,
        previous=previous,
        absolute_change=absolute_change,
        percent_change=percent_change,
        comparison_gap_days=comparison_gap_days,
        comparison_gap_weeks=(
            round(comparison_gap_days / 7, 4) if comparison_gap_days is not None else None
        ),
        comparison_comparable=comparison_comparable,
        data_status=(
            "no_data"
            if latest is None
            else "stale"
            if age_days is not None and age_days > 35
            else "fresh"
        ),
        observation_age_days=age_days,
        sources=source_items,
        population_denominator=denominator,
        windows=(
            [
                _observed_window(
                    all_points,
                    latest_week=latest.week,
                    weeks=weeks,
                    population=denominator.get("population"),
                )
                for weeks in (4, 12)
            ]
            if latest
            else []
        ),
    )


@router.get(
    "/analytics/current-reference",
    response_model=CurrentOfficialReferenceResponse,
)
async def analytics_current_reference(
    session: SessionDep,
    disease: Disease,
    territory: str = Query(default="national", min_length=2, max_length=12),
) -> CurrentOfficialReferenceResponse:
    """Return the latest official BES context without changing municipal case semantics."""

    normalized, scope, _ = _territory_scope(territory)
    reference_code = normalized
    geographic_context_only = False
    direct_row: EpidemiologicalBulletinAggregate | None = None
    if scope == "municipality":
        municipality = await session.get(Municipality, normalized)
        if municipality is None:
            raise DomainError("territory_not_found", "El municipio DIVIPOLA no existe", 404)
        direct_row = await session.scalar(
            select(EpidemiologicalBulletinAggregate)
            .where(
                EpidemiologicalBulletinAggregate.territory_code == normalized,
                EpidemiologicalBulletinAggregate.disease == disease,
            )
            .order_by(
                desc(EpidemiologicalBulletinAggregate.epidemiological_year),
                desc(EpidemiologicalBulletinAggregate.epidemiological_week),
                desc(EpidemiologicalBulletinAggregate.created_at),
                desc(EpidemiologicalBulletinAggregate.id),
            )
            .limit(1)
        )
        if direct_row is None:
            reference_code = municipality.department_code
            geographic_context_only = True

    row = direct_row or await session.scalar(
        select(EpidemiologicalBulletinAggregate)
        .where(
            EpidemiologicalBulletinAggregate.territory_code == reference_code,
            EpidemiologicalBulletinAggregate.disease == disease,
        )
        .order_by(
            desc(EpidemiologicalBulletinAggregate.epidemiological_year),
            desc(EpidemiologicalBulletinAggregate.epidemiological_week),
            desc(EpidemiologicalBulletinAggregate.created_at),
            desc(EpidemiologicalBulletinAggregate.id),
        )
        .limit(1)
    )
    if row is None:
        raise DomainError(
            "current_reference_not_found",
            "El BES no publico una referencia elegible para el territorio y evento",
            404,
        )
    source = await session.get(DataSource, row.source_id)
    age_days = max(0, (date.today() - row.period_end).days)
    limitations = [
        "Cifras preliminares sujetas a ajustes posteriores de las entidades territoriales.",
        "La referencia BES no sustituye la serie municipal ni se usa como prediccion operativa.",
    ]
    if geographic_context_only:
        limitations.append(
            "El INS publico este corte a nivel departamental; se muestra solo como contexto "
            "del municipio seleccionado."
        )
    if row.observed_cases is None:
        limitations.append(
            "La tabla publica acumulado observado y esperado, pero no un conteo semanal observado."
        )
    return CurrentOfficialReferenceResponse(
        requested_territory=normalized,
        reference_territory_code=row.territory_code,
        reference_territory_name=row.territory_name,
        reference_territory_level=row.territory_level,
        geographic_context_only=geographic_context_only,
        disease=disease,
        event_label=row.event_label,
        epidemiological_year=row.epidemiological_year,
        epidemiological_week=row.epidemiological_week,
        period_start=row.period_start,
        period_end=row.period_end,
        cumulative_cases=row.cumulative_cases,
        expected_cases=row.expected_cases,
        observed_cases=row.observed_cases,
        comparison_basis=row.comparison_basis,
        is_preliminary=row.is_preliminary,
        data_status="current" if age_days <= 21 else "stale",
        age_days=age_days,
        source_name=source.name if source else "Boletin Epidemiologico Semanal (INS)",
        source_document_url=row.source_document_url,
        source_page=row.source_page,
        limitations=limitations,
    )


@router.get("/analytics/series", response_model=AnalyticsSeriesResponse)
async def analytics_series(
    session: SessionDep,
    disease: Disease,
    territory: str = Query(default="national", min_length=2, max_length=12),
    date_from: Annotated[date | None, Query(alias="from")] = None,
    date_to: Annotated[date | None, Query(alias="to")] = None,
) -> AnalyticsSeriesResponse:
    if date_from and date_to and date_from > date_to:
        raise DomainError("invalid_date_range", "'from' no puede ser posterior a 'to'", 422)
    normalized, scope, points, denominator = await _observed_series(
        session,
        territory,
        disease,
        date_from,
        date_to,
    )
    return AnalyticsSeriesResponse(
        territory=normalized,
        scope=scope,
        disease=disease,
        points=points,
        metadata={
            "status": "ok" if points else "no_data",
            "aggregation": "sum of observed municipal cases by epidemiological week",
            "synthetic_values": False,
            "population_denominator": denominator,
            "municipality_count_semantics": "municipalities with notified case rows",
        },
    )


@router.get("/analytics/forecast-series", response_model=AnalyticsForecastSeriesResponse)
async def analytics_forecast_series(
    session: SessionDep,
    disease: Disease,
    territory: str = Query(default="national", min_length=2, max_length=12),
    horizon: int = Query(default=4, ge=3, le=4),
) -> AnalyticsForecastSeriesResponse:
    normalized, scope, territory_filter = _territory_scope(territory)
    base_statement = (
        select(Forecast, ModelVersion)
        .join(Municipality, Municipality.code == Forecast.municipality_code)
        .join(ModelVersion, ModelVersion.id == Forecast.model_version_id)
        .where(
            Forecast.disease == disease,
            Forecast.horizon_weeks == horizon,
            ModelVersion.stage == "champion",
        )
    )
    if territory_filter is not None:
        base_statement = base_statement.where(territory_filter)
    rows = (
        await session.execute(
            base_statement.where(_operational_forecast_filter()).order_by(
                Forecast.target_week,
                ModelVersion.version,
                Forecast.municipality_code,
            )
        )
    ).all()
    forecast_mode = "operational"
    if not rows:
        latest_issued_at = await session.scalar(
            base_statement.with_only_columns(func.max(Forecast.issued_at)).order_by(None)
        )
        if latest_issued_at is not None:
            rows = (
                await session.execute(
                    base_statement.where(Forecast.issued_at == latest_issued_at).order_by(
                        Forecast.target_week,
                        ModelVersion.version,
                        Forecast.municipality_code,
                    )
                )
            ).all()
            if rows:
                forecast_mode = "retrospective_research"
    buckets: dict[tuple[date, str], dict] = {}
    for forecast, model in rows:
        key = (forecast.target_week, model.version)
        bucket = buckets.setdefault(
            key,
            {
                "predicted": 0.0,
                "lower": 0.0,
                "upper": 0.0,
                "probability": 0.0,
                "components": {},
                "municipalities": 0,
            },
        )
        bucket["predicted"] += forecast.predicted_cases
        bucket["lower"] += forecast.interval_lower
        bucket["upper"] += forecast.interval_upper
        bucket["probability"] = max(bucket["probability"], forecast.outbreak_probability)
        bucket["municipalities"] += 1
        for name, value in forecast.component_predictions.items():
            if isinstance(value, int | float):
                bucket["components"][name] = bucket["components"].get(name, 0.0) + float(value)
    points = [
        AnalyticsForecastPoint(
            target_week=target_week,
            predicted_cases=round(bucket["predicted"], 3),
            lower_bound=round(bucket["lower"], 3),
            upper_bound=round(bucket["upper"], 3),
            max_outbreak_probability=round(bucket["probability"], 4),
            component_predictions={
                name: round(value, 3) for name, value in bucket["components"].items()
            },
            municipalities=bucket["municipalities"],
            model_version=version,
        )
        for (target_week, version), bucket in sorted(buckets.items())
    ]
    cutoffs = [forecast.observation_cutoff for forecast, _ in rows if forecast.observation_cutoff]
    observation_ages = [
        forecast.observation_age_days
        for forecast, _ in rows
        if forecast.observation_age_days is not None
    ]
    is_operational = bool(rows) and forecast_mode == "operational"
    if is_operational:
        message = "Pronostico champion vigente y elegible para apoyo operativo."
    elif rows:
        message = (
            "Serie retrospectiva del champion mas reciente; sirve para investigacion y "
            "contraste, no para alertas operativas vigentes."
        )
    else:
        message = "No existe un pronostico champion para los filtros solicitados."
    return AnalyticsForecastSeriesResponse(
        territory=normalized,
        scope=scope,
        disease=disease,
        horizon=horizon,
        points=points,
        metadata={
            "status": (
                "ok"
                if is_operational
                else "retrospective_research"
                if points
                else "no_operational_forecasts"
            ),
            "forecast_mode": forecast_mode,
            "operationally_eligible": is_operational,
            "observation_cutoff": max(cutoffs).isoformat() if cutoffs else None,
            "observation_age_days": max(observation_ages) if observation_ages else None,
            "message": message,
            "case_aggregation": "sum",
            "interval_aggregation": "sum of marginal municipal bounds",
            "risk_aggregation": "maximum calibrated municipal probability",
            "synthetic_values": False,
        },
    )


@router.get(
    "/analytics/historical-territories",
    response_model=HistoricalTerritoriesResponse,
)
async def historical_territories(
    session: SessionDep,
    disease: Disease,
    department: str | None = Query(default=None, pattern=r"^\d{2}$"),
    search: str | None = Query(default=None, min_length=1, max_length=160),
    limit: int = Query(default=1200, ge=1, le=2000),
) -> HistoricalTerritoriesResponse:
    """List municipalities that have observed rows for a disease.

    This catalog is intentionally independent from the operational forecast
    layer.  Its municipal cutoff and case values describe notifications only;
    they must never be interpreted as a risk score.
    """

    observation_summary = (
        select(
            EpidemiologicalObservation.municipality_code.label("municipality_code"),
            func.min(EpidemiologicalObservation.week_start).label("first_week"),
            func.max(EpidemiologicalObservation.week_start).label("latest_week"),
            func.count(EpidemiologicalObservation.id).label("observed_weeks"),
            func.sum(EpidemiologicalObservation.cases).label("total_cases"),
        )
        .where(EpidemiologicalObservation.disease == disease)
        .group_by(EpidemiologicalObservation.municipality_code)
        .subquery()
    )
    latest_observation = EpidemiologicalObservation
    statement = (
        select(
            Municipality,
            observation_summary.c.first_week,
            observation_summary.c.latest_week,
            observation_summary.c.observed_weeks,
            observation_summary.c.total_cases,
            latest_observation.cases,
            latest_observation.is_preliminary,
            latest_observation.quality_score,
        )
        .join(
            observation_summary,
            observation_summary.c.municipality_code == Municipality.code,
        )
        .join(
            latest_observation,
            and_(
                latest_observation.municipality_code == Municipality.code,
                latest_observation.disease == disease,
                latest_observation.week_start == observation_summary.c.latest_week,
            ),
        )
    )
    count_statement = (
        select(func.count(func.distinct(EpidemiologicalObservation.municipality_code)))
        .join(
            Municipality,
            Municipality.code == EpidemiologicalObservation.municipality_code,
        )
        .where(EpidemiologicalObservation.disease == disease)
    )
    if department is not None:
        statement = statement.where(Municipality.department_code == department)
        count_statement = count_statement.where(Municipality.department_code == department)
    if search is not None:
        normalized_search = search.strip().lower()
        search_filter = or_(
            Municipality.code.contains(normalized_search),
            func.lower(Municipality.name).contains(normalized_search),
            func.lower(Municipality.department_name).contains(normalized_search),
        )
        statement = statement.where(search_filter)
        count_statement = count_statement.where(search_filter)
    total = int(await session.scalar(count_statement) or 0)
    statement = statement.order_by(
        Municipality.department_name,
        Municipality.name,
        Municipality.code,
    ).limit(limit)
    rows = (await session.execute(statement)).all()
    items = [
        HistoricalTerritoryItemResponse(
            cod_dane=municipality.code,
            municipality=municipality.name,
            department_code=municipality.department_code,
            department=municipality.department_name,
            population=municipality.population,
            latitude=municipality.latitude,
            longitude=municipality.longitude,
            first_week=first_week,
            latest_week=latest_week,
            observation_rows=int(observed_weeks or 0),
            total_observed_cases=int(total_cases or 0),
            latest_observed_cases=int(latest_cases or 0),
            latest_is_preliminary=bool(latest_is_preliminary),
            latest_quality_score=float(latest_quality_score),
        )
        for (
            municipality,
            first_week,
            latest_week,
            observed_weeks,
            total_cases,
            latest_cases,
            latest_is_preliminary,
            latest_quality_score,
        ) in rows
    ]
    return HistoricalTerritoriesResponse(
        disease=disease,
        total=total,
        items=items,
        metadata={
            "status": "ok" if items else "no_data",
            "data_kind": "historical_observations",
            "risk_included": False,
            "forecast_eligibility_required": False,
            "latest_cutoff_semantics": "latest observed week for each municipality",
            "case_semantics": "aggregated notified cases; absent weeks are not inferred as zero",
            "synthetic_values": False,
            "returned": len(items),
            "limit": limit,
        },
    )


async def _query_risk_map(
    session: SessionDep,
    disease: Disease,
    horizon: int,
    *,
    operational_only: bool,
) -> list[tuple[Forecast, Municipality, ModelVersion]]:
    latest = (
        select(
            Forecast.municipality_code.label("municipality_code"),
            func.max(Forecast.issued_at).label("issued_at"),
        )
        .join(ModelVersion, ModelVersion.id == Forecast.model_version_id)
        .where(
            Forecast.disease == disease,
            Forecast.horizon_weeks == horizon,
            _champion_forecast_clause(operational_only=operational_only),
        )
        .group_by(Forecast.municipality_code)
        .subquery()
    )
    statement = (
        select(Forecast, Municipality, ModelVersion)
        .join(
            latest,
            and_(
                latest.c.municipality_code == Forecast.municipality_code,
                latest.c.issued_at == Forecast.issued_at,
            ),
        )
        .join(Municipality, Municipality.code == Forecast.municipality_code)
        .join(ModelVersion, ModelVersion.id == Forecast.model_version_id)
        .where(
            Forecast.disease == disease,
            Forecast.horizon_weeks == horizon,
            _champion_forecast_clause(operational_only=operational_only),
        )
        .order_by(desc(Forecast.outbreak_probability))
    )
    return list((await session.execute(statement)).all())


@router.get("/risk/map", response_model=list[RiskMapItem])
async def risk_map(
    session: SessionDep,
    disease: Disease,
    horizon: int = Query(default=4, ge=3, le=4),
    include_research: bool = Query(
        default=True,
        description=(
            "Si no hay pronósticos operativos vigentes, devolver el último champion "
            "retrospectivo etiquetado como research."
        ),
    ),
) -> list[RiskMapItem]:
    rows = await _query_risk_map(session, disease, horizon, operational_only=True)
    if not rows and include_research:
        rows = await _query_risk_map(session, disease, horizon, operational_only=False)
    return [_risk_item(forecast, municipality, version) for forecast, municipality, version in rows]


async def _latest_forecast(
    session: SessionDep,
    cod_dane: str,
    disease: Disease,
    horizon: int,
    *,
    include_research: bool = True,
) -> tuple[Forecast, Municipality, ModelVersion]:
    for operational_only in (True, False) if include_research else (True,):
        statement = (
            select(Forecast, Municipality, ModelVersion)
            .join(Municipality, Municipality.code == Forecast.municipality_code)
            .join(ModelVersion, ModelVersion.id == Forecast.model_version_id)
            .where(
                Forecast.municipality_code == cod_dane,
                Forecast.disease == disease,
                Forecast.horizon_weeks == horizon,
                _champion_forecast_clause(operational_only=operational_only),
            )
            .order_by(desc(Forecast.issued_at))
            .limit(1)
        )
        row = (await session.execute(statement)).one_or_none()
        if row is not None:
            return row
    raise DomainError(
        "forecast_not_found", "No existe una predicción para los filtros solicitados", 404
    )


@router.get("/risk/municipalities/{cod_dane}", response_model=RiskMapItem)
async def municipality_risk(
    cod_dane: str,
    session: SessionDep,
    disease: Disease,
    horizon: int = Query(default=4, ge=3, le=4),
    include_research: bool = Query(default=True),
) -> RiskMapItem:
    forecast, municipality, version = await _latest_forecast(
        session, cod_dane, disease, horizon, include_research=include_research
    )
    return _risk_item(forecast, municipality, version)


@router.get(
    "/risk/municipalities/{cod_dane}/history",
    response_model=list[HistoricalPointResponse],
)
async def municipality_history(
    cod_dane: str,
    session: SessionDep,
    disease: Disease,
    date_from: Annotated[date | None, Query(alias="from")] = None,
    date_to: Annotated[date | None, Query(alias="to")] = None,
) -> list[HistoricalPointResponse]:
    statement = select(EpidemiologicalObservation).where(
        EpidemiologicalObservation.municipality_code == cod_dane,
        EpidemiologicalObservation.disease == disease,
    )
    if date_from:
        statement = statement.where(EpidemiologicalObservation.week_start >= date_from)
    if date_to:
        statement = statement.where(EpidemiologicalObservation.week_start <= date_to)
    observations = list(
        (await session.scalars(statement.order_by(EpidemiologicalObservation.week_start))).all()
    )
    return [
        HistoricalPointResponse(
            date=item.week_start,
            epidemiological_week=item.epidemiological_week,
            observed=item.cases,
            is_preliminary=item.is_preliminary,
            quality_score=item.quality_score,
        )
        for item in observations
    ]


@router.get("/risk/municipalities/{cod_dane}/explanation", response_model=ExplanationResponse)
async def municipality_explanation(
    cod_dane: str,
    session: SessionDep,
    disease: Disease,
    horizon: int = Query(default=4, ge=3, le=4),
    include_research: bool = Query(default=True),
) -> ExplanationResponse:
    forecast, _, version = await _latest_forecast(
        session, cod_dane, disease, horizon, include_research=include_research
    )
    return ExplanationResponse(
        forecast_id=forecast.id,
        cod_dane=cod_dane,
        disease=disease,
        horizon=horizon,
        risk_score=round(forecast.outbreak_probability * 100, 2),
        drivers=forecast.drivers,
        component_predictions=forecast.component_predictions,
        warnings=forecast.warnings,
        model_version=version.version,
        observation_cutoff=getattr(forecast, "observation_cutoff", None),
        operationally_eligible=getattr(forecast, "operationally_eligible", True),
        probability_calibration=version.metrics.get("probability_calibration", {}),
    )


@router.get(
    "/models/readiness/portfolio",
    response_model=ModelPortfolioReadinessResponse,
)
async def model_portfolio_readiness(
    session: SessionDep,
) -> ModelPortfolioReadinessResponse:
    """Expose what is really trainable, trained and operational per disease."""

    return ModelPortfolioReadinessResponse.model_validate(
        await build_model_portfolio_readiness(session)
    )


@router.get("/models/{disease}", response_model=ModelMetadataResponse)
async def model_metadata(
    disease: Disease,
    session: SessionDep,
    horizon: int = Query(default=4, ge=3, le=4),
) -> ModelMetadataResponse:
    model = await session.scalar(
        select(ModelVersion)
        .where(
            ModelVersion.disease == disease,
            ModelVersion.horizon_weeks == horizon,
            ModelVersion.stage == "champion",
        )
        .order_by(desc(ModelVersion.activated_at))
        .limit(1)
    )
    if model is None:
        raise DomainError("model_not_found", "No hay una versión registrada para este modelo", 404)
    return ModelMetadataResponse(
        disease=disease,
        horizon=horizon,
        version=model.version,
        status=model.stage,
        trained_at=model.created_at,
        activated_at=model.activated_at,
        metrics=model.metrics,
        features=model.feature_names,
        training_period={"from": model.training_started_on, "to": model.training_ended_on},
        data_fingerprint=model.data_fingerprint,
        artifact_sha256=model.metrics.get("_trace", {}).get("artifact_sha256"),
        pipeline_fingerprint=model.metrics.get("_trace", {}).get("pipeline_fingerprint"),
    )


@router.get("/models/{disease}/versions", response_model=list[ModelVersionSummary])
async def model_versions(
    disease: Disease,
    session: SessionDep,
    horizon: int = Query(default=4, ge=3, le=4),
) -> list[ModelVersionSummary]:
    models = list(
        (
            await session.scalars(
                select(ModelVersion)
                .where(
                    ModelVersion.disease == disease,
                    ModelVersion.horizon_weeks == horizon,
                )
                .order_by(desc(ModelVersion.created_at))
            )
        ).all()
    )
    return [
        ModelVersionSummary(
            disease=disease,
            horizon=horizon,
            version=model.version,
            stage=model.stage,
            created_at=model.created_at,
            activated_at=model.activated_at,
            data_fingerprint=model.data_fingerprint,
            artifact_sha256=model.metrics.get("_trace", {}).get("artifact_sha256"),
            temporal_mae=model.metrics.get("mae"),
            territorial_mae=model.metrics.get("territorial_mae"),
        )
        for model in models
    ]


@router.get(
    "/models/{disease}/{horizon}/versions/{version}/trace",
    response_model=ModelTraceResponse,
)
async def model_trace(
    disease: Disease,
    horizon: int,
    version: str,
    session: SessionDep,
    settings: Annotated[Settings, Depends(get_runtime_settings)],
) -> ModelTraceResponse:
    if horizon not in (3, 4):
        raise DomainError("invalid_horizon", "Solo se admiten horizontes de 3 y 4 semanas", 422)
    model = await session.scalar(
        select(ModelVersion).where(
            ModelVersion.disease == disease,
            ModelVersion.horizon_weeks == horizon,
            ModelVersion.version == version,
        )
    )
    if model is None:
        raise DomainError("model_not_found", "La version solicitada no existe", 404)
    registry = ModelRegistry(settings.model_registry_path)
    try:
        verification = registry.verify(disease, horizon, version)
        manifest = verification["manifest"]
        integrity_valid = True
    except (OSError, FileNotFoundError, ValueError):
        manifest = {}
        integrity_valid = False
    trace = model.metrics.get("_trace", {})
    config = manifest.get("config", trace.get("config", {}))
    return ModelTraceResponse(
        disease=disease,
        horizon=horizon,
        version=version,
        stage=model.stage,
        artifact_ref=f"models/{disease}/h{horizon}/{version}",
        artifact_sha256=str(manifest.get("artifact_sha256") or trace.get("artifact_sha256") or ""),
        artifact_integrity_valid=integrity_valid,
        data_fingerprint=model.data_fingerprint,
        dataset_snapshot_sha256=manifest.get("dataset_snapshot_sha256")
        or trace.get("dataset_snapshot_sha256"),
        pipeline_fingerprint=manifest.get("pipeline_fingerprint")
        or trace.get("pipeline_fingerprint"),
        training_job_id=manifest.get("training_job_id") or trace.get("training_job_id"),
        seed=config.get("random_state"),
        parameters=config,
        runtime=manifest.get("runtime", trace.get("runtime", {})),
        metrics={key: value for key, value in model.metrics.items() if key != "_trace"},
        fold_metrics=manifest.get("fold_metrics", trace.get("fold_metrics", [])),
        dataset=_public_dataset_lineage(manifest.get("dataset_manifest", {})),
        readiness=manifest.get("model_readiness", {}),
        features=model.feature_names,
        training_period={"from": model.training_started_on, "to": model.training_ended_on},
        created_at=model.created_at,
        activated_at=model.activated_at,
    )


@router.post(
    "/models/{disease}/{horizon}/versions/{version}/activate",
    response_model=ModelActivationResponse,
)
async def activate_model_version(
    disease: Disease,
    horizon: int,
    version: str,
    _: Operator,
    session: SessionDep,
    settings: Annotated[Settings, Depends(get_runtime_settings)],
) -> ModelActivationResponse:
    if horizon not in (3, 4):
        raise DomainError("invalid_horizon", "Solo se admiten horizontes de 3 y 4 semanas", 422)
    await acquire_model_promotion_locks(session, disease, (horizon,))
    model = await session.scalar(
        select(ModelVersion)
        .where(
            ModelVersion.disease == disease,
            ModelVersion.horizon_weeks == horizon,
            ModelVersion.version == version,
        )
        .with_for_update()
    )
    if model is None:
        raise DomainError("model_not_found", "La version solicitada no existe", 404)
    registry = ModelRegistry(settings.model_registry_path)
    previous_pointer = registry.latest_version(disease, horizon)
    try:
        registry.activate(disease, horizon, version)
        champions = list(
            (
                await session.scalars(
                    select(ModelVersion).where(
                        ModelVersion.disease == disease,
                        ModelVersion.horizon_weeks == horizon,
                        ModelVersion.stage == "champion",
                        ModelVersion.id != model.id,
                    )
                )
            ).all()
        )
        for champion in champions:
            champion.stage = "archived"
        model.stage = "champion"
        model.activated_at = datetime.now(UTC)
        await session.commit()
        await session.refresh(model)
    except Exception as exc:
        await session.rollback()
        try:
            await acquire_model_promotion_locks(session, disease, (horizon,))
            registry.restore_latest(
                disease,
                horizon,
                previous_pointer,
                expected_current=version,
            )
            await session.commit()
        except Exception:
            await session.rollback()
        raise DomainError(
            "model_activation_failed",
            "No fue posible verificar y activar el artefacto solicitado",
            409,
        ) from exc
    return ModelActivationResponse(
        disease=disease,
        horizon=horizon,
        version=version,
        stage="champion",
        activated_at=model.activated_at,
    )


@router.post(
    "/models/train",
    response_model=TrainingJobResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def request_training(
    payload: TrainingRequest,
    user: Operator,
    session: SessionDep,
) -> TrainingJobResponse:
    horizons = sorted(set(payload.horizons))
    if any(horizon not in (3, 4) for horizon in horizons):
        raise DomainError("invalid_horizon", "Solo se admiten horizontes de 3 y 4 semanas", 422)
    job = ModelTrainingRun(
        disease=payload.disease,
        horizons=horizons,
        requested_by=user.id,
        parameters={"force": payload.force},
    )
    session.add(job)
    await session.commit()
    await session.refresh(job)
    return TrainingJobResponse(
        job_id=job.id,
        disease=job.disease,
        horizons=job.horizons,
        status=job.status,
        created_at=job.created_at,
    )


@router.get("/models/train/{job_id}", response_model=TrainingJobResponse)
async def training_status(job_id: str, _: Operator, session: SessionDep) -> TrainingJobResponse:
    job = await session.get(ModelTrainingRun, job_id)
    if job is None:
        raise DomainError("training_job_not_found", "El entrenamiento solicitado no existe", 404)
    return TrainingJobResponse.model_validate(job, from_attributes=True)


def _public_dataset_lineage(manifest: dict) -> dict:
    """Remove internal paths while retaining content-addressed provenance."""

    allowed = {
        "schema_version",
        "disease",
        "fingerprint",
        "extracted_at",
        "rows",
        "observed_case_rows",
        "missing_case_weeks",
        "territories",
        "week_start",
        "week_end",
        "columns",
        "source_ids",
        "ingestion_run_ids",
        "temporal_join_policy",
        "missing_case_policy",
        "covariate_granularity",
        "feature_semantics",
        "covariate_coverage",
        "known_data_gaps",
    }
    return {key: value for key, value in manifest.items() if key in allowed}


@router.get("/risk/alerts", response_model=list[AlertEventResponse])
async def epidemiological_alerts(
    response: Response,
    session: SessionDep,
    disease: Disease | None = None,
    alert_status: Annotated[str | None, Query(alias="status", max_length=30)] = None,
    territory: str | None = Query(default=None, min_length=2, max_length=12),
    department: str | None = Query(default=None, pattern=r"^\d{2}$"),
    cod_dane: str | None = Query(default=None, pattern=r"^\d{5}$"),
    horizon: int | None = Query(default=None, ge=3, le=4),
    target_from: Annotated[date | None, Query(alias="from")] = None,
    target_to: Annotated[date | None, Query(alias="to")] = None,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
) -> list[AlertEventResponse]:
    if target_from and target_to and target_from > target_to:
        raise DomainError("invalid_date_range", "'from' no puede ser posterior a 'to'", 422)
    filters = []
    if disease:
        filters.append(Forecast.disease == disease)
    if territory:
        _, _, territory_filter = _territory_scope(territory)
        if territory_filter is not None:
            filters.append(territory_filter)
    if department:
        filters.append(Municipality.department_code == department)
    if cod_dane:
        filters.append(Municipality.code == cod_dane)
    if horizon is not None:
        filters.append(Forecast.horizon_weeks == horizon)
    if target_from:
        filters.append(Forecast.target_week >= target_from)
    if target_to:
        filters.append(Forecast.target_week <= target_to)
    if alert_status:
        expired_or_withheld = or_(
            Forecast.operationally_eligible.is_(False),
            Forecast.target_week < date.today(),
        )
        if alert_status == "archived":
            filters.append(
                or_(
                    AlertEvent.status == "archived",
                    and_(
                        AlertEvent.status.in_(("open", "active")),
                        expired_or_withheld,
                    ),
                )
            )
        elif alert_status in ("open", "active"):
            filters.extend(
                [
                    AlertEvent.status == alert_status,
                    Forecast.operationally_eligible.is_(True),
                    Forecast.target_week >= date.today(),
                ]
            )
        else:
            filters.append(AlertEvent.status == alert_status)
    total = int(
        await session.scalar(
            select(func.count(AlertEvent.id))
            .join(Forecast, Forecast.id == AlertEvent.forecast_id)
            .join(Municipality, Municipality.code == Forecast.municipality_code)
            .where(*filters)
        )
        or 0
    )
    response.headers["X-Total-Count"] = str(total)
    statement = (
        select(AlertEvent, Forecast, Municipality)
        .join(Forecast, Forecast.id == AlertEvent.forecast_id)
        .join(Municipality, Municipality.code == Forecast.municipality_code)
        .where(*filters)
        .order_by(
            Forecast.target_week.desc(),
            Forecast.issued_at.desc(),
            AlertEvent.created_at.desc(),
            AlertEvent.id.desc(),
        )
        .offset(offset)
        .limit(limit)
    )
    rows = (await session.execute(statement)).all()
    return [
        AlertEventResponse(
            id=alert.id,
            forecast_id=forecast.id,
            cod_dane=municipality.code,
            municipality=municipality.name,
            department=municipality.department_name,
            disease=forecast.disease,
            horizon=forecast.horizon_weeks,
            risk_score=round(forecast.outbreak_probability * 100, 2),
            risk_level=RISK_TRANSLATION.get(forecast.risk_level, forecast.risk_level),
            predicted_cases=forecast.predicted_cases,
            lower_bound=forecast.interval_lower,
            upper_bound=forecast.interval_upper,
            drivers=forecast.drivers,
            status=(
                "archived"
                if (
                    alert.status in ("open", "active")
                    and (
                        not forecast.operationally_eligible
                        or forecast.target_week < date.today()
                    )
                )
                else alert.status
            ),
            reviewed_at=alert.reviewed_at,
            reviewed_by=alert.reviewed_by,
            review_notes=alert.review_notes,
            created_at=alert.created_at,
            issued_at=forecast.issued_at,
            target_week=forecast.target_week,
            operationally_eligible=(
                forecast.operationally_eligible and forecast.target_week >= date.today()
            ),
        )
        for alert, forecast, municipality in rows
    ]


@router.post("/risk/alerts/{alert_id}/review", response_model=AlertEventResponse)
async def review_epidemiological_alert(
    alert_id: str,
    payload: AlertReviewRequest,
    user: Operator,
    session: SessionDep,
) -> AlertEventResponse:
    row = (
        await session.execute(
            select(AlertEvent, Forecast, Municipality)
            .join(Forecast, Forecast.id == AlertEvent.forecast_id)
            .join(Municipality, Municipality.code == Forecast.municipality_code)
            .where(AlertEvent.id == alert_id)
        )
    ).one_or_none()
    if row is None:
        raise DomainError("alert_not_found", "La alerta solicitada no existe", 404)
    alert, forecast, municipality = row
    alert.status = payload.status
    alert.review_notes = payload.notes
    alert.reviewed_by = user.id
    alert.reviewed_at = datetime.now(UTC)
    await session.commit()
    await session.refresh(alert)
    return AlertEventResponse(
        id=alert.id,
        forecast_id=forecast.id,
        cod_dane=municipality.code,
        municipality=municipality.name,
        department=municipality.department_name,
        disease=forecast.disease,
        horizon=forecast.horizon_weeks,
        risk_score=round(forecast.outbreak_probability * 100, 2),
        risk_level=RISK_TRANSLATION.get(forecast.risk_level, forecast.risk_level),
        predicted_cases=forecast.predicted_cases,
        lower_bound=forecast.interval_lower,
        upper_bound=forecast.interval_upper,
        drivers=forecast.drivers,
        status=alert.status,
        reviewed_at=alert.reviewed_at,
        reviewed_by=alert.reviewed_by,
        review_notes=alert.review_notes,
        created_at=alert.created_at,
        issued_at=forecast.issued_at,
        target_week=forecast.target_week,
        operationally_eligible=(
            forecast.operationally_eligible and forecast.target_week >= date.today()
        ),
    )
