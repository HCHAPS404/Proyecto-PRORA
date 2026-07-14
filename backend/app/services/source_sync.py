"""Queue and execute reproducible ingestion of verified official publications."""

from __future__ import annotations

import hashlib
import tempfile
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, time, timedelta
from functools import partial
from typing import Any

import anyio
import httpx
from sqlalchemy import select, text as sa_text
from sqlalchemy.ext.asyncio import AsyncSession

from app.connectors import (
    SIVIGILA_2024_EVENT_FILES,
    SIVIGILA_MICRODATA_DISCOVERY_URL,
    Aggregate,
    DANECNPVConnector,
    DIVIPOLAConnector,
    Filter,
    IDEAMClimateConnector,
    IDEAMStationsConnector,
    Operator,
    PAIConnector,
    SIVIGILAConnector,
    SafeQuery,
    SocrataClient,
    sivigila_2024_event_files,
)
from app.connectors.territorial_sivigila import (
    FEDERATION_SOURCE_ID,
    TerritorialSourceProfile,
    disease_from_event_and_name,
    extract_cases,
    extract_event_code,
    extract_year_week,
    pad_divipola,
    profile_by_source_id,
    territorial_profiles,
)
from app.core.config import Settings
from app.core.errors import DomainError
from app.ingestion.bes import BES_ADAPTER_VERSION, BESRecord, parse_bes_publication
from app.ingestion.pai_files import (
    PAI_2026_CONTRACT,
    PAI_ADAPTER_VERSION,
    PAI_HISTORY_CONTRACT,
    PAIFileContract,
    PAIMunicipalRecord,
    parse_pai_publication,
)
from app.ingestion.sivigila_microdata import (
    SIVIGILA_MICRODATA_ADAPTER_VERSION,
    ParsedSIVIGILAMicrodata,
    parse_sivigila_2024_workbook,
)
from app.ingestion.snapshots import (
    RawFileSnapshotWriter,
    RawSnapshotWriter,
    SnapshotArtifact,
)
from app.models.epidemiology import (
    DataSource,
    EpidemiologicalBulletinAggregate,
    IngestionRun,
    Municipality,
    PipelineStatus,
    SourceStatus,
)
from app.schemas.sources import SourceSyncRequest
from app.services.canonical_store import (
    CanonicalValidationError,
    ClimateBucket,
    MunicipalityResolver,
    SIVIGILACanonical,
    add_quarantine,
    canonicalize_cnpv_class,
    canonicalize_pai,
    canonicalize_sivigila,
    climate_week_key,
    epidemiological_week_start,
    raw_record_sha256,
    store_snapshot,
    upsert_climate_buckets,
    upsert_cnpv,
    upsert_irca_batch,
    upsert_municipal_pai_batch,
    upsert_pai,
    upsert_sivigila_batch,
    upsert_station,
)

_MONTH_NAME_TO_NUMBER = {
    "ENERO": 1,
    "FEBRERO": 2,
    "MARZO": 3,
    "ABRIL": 4,
    "MAYO": 5,
    "JUNIO": 6,
    "JULIO": 7,
    "AGOSTO": 8,
    "SEPTIEMBRE": 9,
    "SETIEMBRE": 9,
    "OCTUBRE": 10,
    "NOVIEMBRE": 11,
    "DICIEMBRE": 12,
}


@dataclass(slots=True)
class SyncOutcome:
    artifact: SnapshotArtifact
    accepted: int
    rejected: int
    canonical_rows: int
    details: dict[str, Any]
    cursor: str | None = None


async def schedule_source_sync(
    session: AsyncSession, source_id: str, request: SourceSyncRequest
) -> IngestionRun:
    source = await session.get(DataSource, source_id)
    if source is None:
        raise DomainError("source_not_found", "La fuente solicitada no existe", 404)
    if source.status == SourceStatus.REQUIRES_CONFIGURATION.value:
        raise DomainError(
            "source_configuration_required",
            str(source.configuration.get("reason", "La fuente requiere configuración.")),
            409,
        )
    if source.status == SourceStatus.DISABLED.value:
        raise DomainError("source_disabled", "La fuente está deshabilitada", 409)
    existing = await session.scalar(
        select(IngestionRun).where(
            IngestionRun.source_id == source_id,
            IngestionRun.status.in_([PipelineStatus.PENDING.value, PipelineStatus.RUNNING.value]),
        )
    )
    if existing is not None:
        raise DomainError(
            "source_sync_already_queued",
            "Ya existe una sincronización pendiente o en ejecución",
            409,
            {"run_id": existing.id},
        )
    run = IngestionRun(
        source_id=source_id,
        status=PipelineStatus.PENDING.value,
        provenance={
            "kind": "official_source_sync",
            "request": request.model_dump(mode="json"),
        },
    )
    session.add(run)
    await session.commit()
    await session.refresh(run)
    return run


# Backward-compatible service name used by integrations created before queueing.
sync_source = schedule_source_sync


async def process_source_sync(
    session: AsyncSession,
    run: IngestionRun,
    settings: Settings,
    *,
    http_client: httpx.AsyncClient | None = None,
) -> IngestionRun:
    run_id = run.id
    source_id = run.source_id
    source = await session.get(DataSource, source_id)
    if source is None:
        raise DomainError("source_not_found", "La fuente solicitada no existe", 404)
    request = SourceSyncRequest.model_validate(run.provenance.get("request", {}))
    run.status = PipelineStatus.RUNNING.value
    run.started_at = datetime.now(UTC)
    await session.commit()
    owns_client = http_client is None
    client = http_client or httpx.AsyncClient(timeout=90.0, follow_redirects=True)
    try:
        outcome = await _dispatch(session, run, source, request, settings, client)
        store_snapshot(session, run, outcome.artifact)
        run.rows_read = outcome.artifact.row_count
        run.rows_accepted = outcome.accepted
        run.rows_rejected = outcome.rejected
        run.checksum = outcome.artifact.sha256
        run.cursor = outcome.cursor
        run.provenance = {
            **dict(run.provenance or {}),
            "snapshot_path": outcome.artifact.object_path,
            "manifest_path": outcome.artifact.manifest_path,
            "snapshot_sha256": outcome.artifact.sha256,
            "schema_sha256": outcome.artifact.schema_sha256,
        }
        run.quality_report = {
            "acceptance_rate": outcome.accepted / max(1, outcome.artifact.row_count),
            "canonical_rows": outcome.canonical_rows,
            "quarantine_rows": outcome.rejected,
            **outcome.details,
        }
        run.finished_at = datetime.now(UTC)
        if outcome.details.get("contract_valid") is False:
            run.status = PipelineStatus.FAILED.value
            run.error_message = "La publicación no coincide con el contrato de parser aprobado"
        elif outcome.artifact.row_count and not outcome.accepted:
            run.status = PipelineStatus.FAILED.value
            run.error_message = "Ninguna fila superó los controles de calidad"
        elif outcome.rejected:
            run.status = PipelineStatus.PARTIAL.value
        else:
            run.status = PipelineStatus.SUCCEEDED.value
        source.last_checked_at = run.finished_at
        if run.status != PipelineStatus.FAILED.value:
            source.last_success_at = run.finished_at
            source.status = SourceStatus.ACTIVE.value
        if outcome.cursor:
            configuration = dict(source.configuration or {})
            configuration["cursor"] = outcome.cursor
            source.configuration = configuration
        await session.commit()
        await session.refresh(run)
        return run
    except Exception as exc:
        await session.rollback()
        persisted = await session.get(IngestionRun, run_id)
        persisted_source = await session.get(DataSource, source_id)
        if persisted is not None:
            persisted.status = PipelineStatus.FAILED.value
            persisted.finished_at = datetime.now(UTC)
            persisted.error_message = str(exc)[:4000]
        if persisted_source is not None:
            persisted_source.status = SourceStatus.DEGRADED.value
            persisted_source.last_checked_at = datetime.now(UTC)
        await session.commit()
        return persisted or run
    finally:
        if owns_client:
            await client.aclose()


async def _dispatch(
    session: AsyncSession,
    run: IngestionRun,
    source: DataSource,
    request: SourceSyncRequest,
    settings: Settings,
    http_client: httpx.AsyncClient,
) -> SyncOutcome:
    if source.id == "dane-divipola":
        return await _sync_divipola(session, run, source, settings, http_client)
    if source.id == "dane-socioeconomic":
        return await _sync_cnpv(session, run, source, settings, http_client)
    if source.id == "sivigila-national":
        return await _sync_sivigila(session, run, source, request, settings, http_client)
    if source.id == "sivigila-microdata-2024":
        return await _sync_sivigila_microdata_2024(
            session, run, source, request, settings, http_client
        )
    if source.id == FEDERATION_SOURCE_ID or profile_by_source_id(source.id) is not None:
        return await _sync_territorial_sivigila(
            session, run, source, request, settings, http_client
        )
    if source.id == "ins-bes-weekly":
        return await _sync_bes(session, run, source, request, settings, http_client)
    if source.id == "pai-national":
        return await _sync_pai(session, run, source, request, settings, http_client)
    if source.id == "pai-municipal-history":
        return await _sync_pai_file(
            session,
            run,
            source,
            request,
            settings,
            http_client,
            PAI_HISTORY_CONTRACT,
        )
    if source.id == "pai-municipal-2026":
        return await _sync_pai_file(
            session,
            run,
            source,
            request,
            settings,
            http_client,
            PAI_2026_CONTRACT,
        )
    if source.id == "pai-valle-municipal":
        return await _sync_pai_territorial_socrata(
            session, run, source, request, settings, http_client
        )
    if source.id == "ins-irca-water-quality":
        return await _sync_irca(session, run, source, request, settings, http_client)
    if source.id == "ideam-stations":
        return await _sync_stations(session, run, source, settings, http_client)
    if source.id in {"ideam-precipitation", "ideam-temperature", "ideam-humidity"}:
        return await _sync_climate(session, run, source, request, settings, http_client)
    raise DomainError(
        "source_processor_unavailable",
        "La fuente no tiene un procesador automático aprobado",
        409,
    )


def _bes_candidate_urls(source: DataSource, request: SourceSyncRequest) -> list[str]:
    configuration = dict(source.configuration or {})
    templates = configuration.get("url_templates")
    if not isinstance(templates, list) or not all(isinstance(item, str) for item in templates):
        raise DomainError(
            "source_contract_mismatch",
            "La fuente BES no tiene plantillas de publicacion verificables",
            409,
        )
    reference = request.to_date or datetime.now(UTC).date()
    year, current_week, _ = reference.isocalendar()
    lookback = min(max(int(configuration.get("lookback_weeks", 10)), 1), 16)
    candidates: list[str] = []
    verified = configuration.get("verified_latest_document")
    if isinstance(verified, str) and verified:
        candidates.append(verified)
    for offset in range(lookback + 1):
        week = current_week - offset
        candidate_year = year
        if week < 1:
            candidate_year -= 1
            week += date(candidate_year, 12, 28).isocalendar().week
        for template in templates:
            url = template.format(year=candidate_year, week=week)
            if url not in candidates:
                candidates.append(url)
    return candidates


async def _download_latest_bes(
    source: DataSource,
    request: SourceSyncRequest,
    http_client: httpx.AsyncClient,
) -> tuple[str, bytes, dict[str, str | None]]:
    maximum_bytes = 35 * 1024 * 1024
    for url in _bes_candidate_urls(source, request):
        try:
            response = await http_client.get(
                url,
                headers={
                    "Accept": "application/pdf",
                    "User-Agent": "PRORA/1.0 (+public-health-research)",
                },
            )
        except httpx.HTTPError:
            continue
        if response.status_code != 200:
            continue
        content = response.content
        if not content.startswith(b"%PDF"):
            continue
        if len(content) > maximum_bytes:
            raise DomainError(
                "source_file_too_large",
                "El boletin BES supera el limite operativo de 35 MB",
                413,
            )
        return (
            url,
            content,
            {
                "etag": response.headers.get("etag"),
                "last_modified": response.headers.get("last-modified"),
                "content_length": response.headers.get("content-length"),
            },
        )
    raise DomainError(
        "source_publication_not_found",
        "No se encontro un boletin epidemiologico oficial reciente dentro de la ventana",
        404,
    )


async def _upsert_bes_records(
    session: AsyncSession,
    run: IngestionRun,
    source_url: str,
    records: list[BESRecord],
) -> None:
    if not records:
        return
    years = {record.epidemiological_year for record in records}
    weeks = {record.epidemiological_week for record in records}
    existing = list(
        (
            await session.scalars(
                select(EpidemiologicalBulletinAggregate).where(
                    EpidemiologicalBulletinAggregate.source_id == run.source_id,
                    EpidemiologicalBulletinAggregate.epidemiological_year.in_(years),
                    EpidemiologicalBulletinAggregate.epidemiological_week.in_(weeks),
                )
            )
        ).all()
    )
    by_key = {
        (
            item.territory_code,
            item.disease,
            item.epidemiological_year,
            item.epidemiological_week,
        ): item
        for item in existing
    }
    for record in records:
        key = (
            record.territory_code,
            record.disease,
            record.epidemiological_year,
            record.epidemiological_week,
        )
        values = {
            "territory_name": record.territory_name,
            "territory_level": record.territory_level,
            "event_label": record.event_label,
            "period_start": record.period_start,
            "period_end": record.period_end,
            "cumulative_cases": record.cumulative_cases,
            "expected_cases": record.expected_cases,
            "observed_cases": record.observed_cases,
            "comparison_basis": record.comparison_basis,
            "is_preliminary": True,
            "source_document_url": source_url,
            "source_page": record.source_page,
            "ingestion_run_id": run.id,
        }
        stored = by_key.get(key)
        if stored is None:
            stored = EpidemiologicalBulletinAggregate(
                source_id=run.source_id,
                territory_code=record.territory_code,
                disease=record.disease,
                epidemiological_year=record.epidemiological_year,
                epidemiological_week=record.epidemiological_week,
                **values,
            )
            session.add(stored)
            by_key[key] = stored
        else:
            for field_name, value in values.items():
                setattr(stored, field_name, value)


async def _sync_bes(
    session: AsyncSession,
    run: IngestionRun,
    source: DataSource,
    request: SourceSyncRequest,
    settings: Settings,
    http_client: httpx.AsyncClient,
) -> SyncOutcome:
    source_url, content, publication = await _download_latest_bes(source, request, http_client)
    writer = RawFileSnapshotWriter(
        root=settings.raw_snapshot_dir,
        source_id=source.id,
        run_id=run.id,
        source_url=source_url,
        media_type="application/pdf",
        filename="source.pdf",
        query=request.model_dump(mode="json"),
        publication={
            "publisher": "Instituto Nacional de Salud - INS",
            **publication,
        },
    )
    try:
        writer.append_chunk(content)
        parsed = await anyio.to_thread.run_sync(
            parse_bes_publication,
            writer.staging_path(),
        )
        artifact = writer.finalize(
            row_count=len(parsed.records),
            schema_descriptor=parsed.schema_descriptor,
            extra={
                "adapter_version": BES_ADAPTER_VERSION,
                "contract_valid": parsed.contract_valid,
                "epidemiological_year": parsed.epidemiological_year,
                "epidemiological_week": parsed.epidemiological_week,
                "period_start": parsed.period_start.isoformat(),
                "period_end": parsed.period_end.isoformat(),
                "diseases_found": parsed.diseases_found,
                "territorial_resolution": "department_or_certified_district",
                "training_panel_merged": False,
            },
        )
    except Exception:
        writer.abort()
        raise
    if parsed.contract_valid:
        await _upsert_bes_records(session, run, source_url, parsed.records)
    return SyncOutcome(
        artifact=artifact,
        accepted=len(parsed.records) if parsed.contract_valid else 0,
        rejected=0 if parsed.contract_valid else len(parsed.records),
        canonical_rows=len(parsed.records) if parsed.contract_valid else 0,
        details={
            "contract_valid": parsed.contract_valid,
            "adapter_version": BES_ADAPTER_VERSION,
            "epidemiological_year": parsed.epidemiological_year,
            "epidemiological_week": parsed.epidemiological_week,
            "period_end": parsed.period_end.isoformat(),
            "diseases_found": parsed.diseases_found,
            "territorial_resolution": "department_or_certified_district",
            "current_reference_only": True,
            "municipal_allocation_performed": False,
        },
        cursor=f"{parsed.epidemiological_year}-W{parsed.epidemiological_week:02d}",
    )


def _socrata_client(
    source: DataSource, settings: Settings, http_client: httpx.AsyncClient
) -> SocrataClient:
    token = settings.socrata_app_token
    return SocrataClient(
        client=http_client,
        app_token=token.get_secret_value() if token else None,
        max_page_size=max(50_000, settings.ingestion_batch_size),
    )


def _publication(metadata: dict[str, Any]) -> dict[str, Any]:
    owner = metadata.get("owner") if isinstance(metadata.get("owner"), dict) else {}
    return {
        "id": metadata.get("id"),
        "name": metadata.get("name"),
        "owner": owner.get("displayName"),
        "rows_updated_at_epoch": metadata.get("rowsUpdatedAt"),
        "metadata_updated_at_epoch": metadata.get("metadataUpdatedAt"),
    }


def _writer(
    settings: Settings,
    source: DataSource,
    run: IngestionRun,
    query: dict[str, Any],
    publication: dict[str, Any] | None = None,
) -> RawSnapshotWriter:
    return RawSnapshotWriter(
        root=settings.raw_snapshot_dir,
        source_id=source.id,
        run_id=run.id,
        source_url=source.endpoint or "",
        dataset_id=source.dataset_id,
        query=query,
        publication=publication,
    )


def _resolve_territorial_municipality(
    resolver: MunicipalityResolver,
    profile: TerritorialSourceProfile,
    row: dict[str, Any],
) -> str | None:
    if profile.fixed_municipality_code:
        code = profile.fixed_municipality_code
        return code if code in resolver.by_code else None
    fields = profile.fields
    code = pad_divipola(
        str(row.get(fields.department_code)) if fields.department_code else None,
        str(row.get(fields.municipality_code)) if fields.municipality_code else None,
    )
    if code and code in resolver.by_code:
        return code
    department = row.get(fields.department_name) if fields.department_name else None
    municipality = row.get(fields.municipality_name) if fields.municipality_name else None
    match = resolver.names(department, municipality)
    return match.code if match is not None else None


def _canonicalize_territorial_row(
    profile: TerritorialSourceProfile,
    resolver: MunicipalityResolver,
    row: dict[str, Any],
) -> SIVIGILACanonical:
    year_week = extract_year_week(row, profile.fields)
    if year_week is None:
        raise CanonicalValidationError("invalid_period", "Año/semana epidemiológica inválidos")
    year, week = year_week
    if year < profile.year_from or year > profile.year_to:
        raise CanonicalValidationError(
            "year_out_of_contract",
            f"Año {year} fuera del contrato {profile.year_from}-{profile.year_to}",
        )
    event_code = extract_event_code(row, profile.fields)
    event_name = (
        str(row.get(profile.fields.event_name)) if profile.fields.event_name else None
    )
    disease = disease_from_event_and_name(
        event_code, event_name, allowed=profile.diseases
    )
    if (
        disease is None
        and len(profile.diseases) == 1
        and not profile.fields.event_code
        and not profile.fields.event_name
    ):
        disease = profile.diseases[0]
    if disease is None:
        raise CanonicalValidationError(
            "event_not_prioritized",
            "Evento fuera de enfermedades priorizadas o nombre inconsistente",
        )
    municipality_code = _resolve_territorial_municipality(resolver, profile, row)
    if municipality_code is None:
        raise CanonicalValidationError(
            "unknown_divipola",
            "No se pudo resolver municipio DIVIPOLA para la fila territorial",
        )
    try:
        cases = extract_cases(row, profile)
    except ValueError as exc:
        raise CanonicalValidationError("invalid_case_count", str(exc)) from exc
    return SIVIGILACanonical(
        municipality_code=municipality_code,
        disease=disease,
        week_start=epidemiological_week_start(year, week),
        epidemiological_week=week,
        epidemiological_year=year,
        cases=cases,
        raw_record_sha256=raw_record_sha256(row),
    )


async def _sync_territorial_profile(
    session: AsyncSession,
    run: IngestionRun,
    source: DataSource,
    profile: TerritorialSourceProfile,
    request: SourceSyncRequest,
    settings: Settings,
    http_client: httpx.AsyncClient,
) -> SyncOutcome:
    client = _socrata_client(source, settings, http_client)
    year_from = max(profile.year_from, (request.from_date or date(profile.year_from, 1, 1)).year)
    year_to = min(
        profile.year_to,
        (request.to_date - timedelta(days=1)).year if request.to_date else profile.year_to,
    )
    if year_from > year_to:
        raise DomainError(
            "source_period_unavailable",
            f"Periodo solicitado fuera del contrato {profile.year_from}-{profile.year_to}",
            422,
        )
    query = SafeQuery(
        filters=(
            Filter(profile.fields.year, Operator.GTE, str(year_from)),
            Filter(profile.fields.year, Operator.LTE, str(year_to)),
        ),
        order_by=(
            (profile.fields.year, "ASC"),
            (profile.fields.week, "ASC"),
        ),
    )
    metadata = await client.fetch_metadata(profile.dataset_id)
    writer = _writer(
        settings,
        source,
        run,
        {
            "dataset_id": profile.dataset_id,
            "year_from": year_from,
            "year_to": year_to,
            "adapter": "territorial_sivigila",
            **query.parameters(),
        },
        _publication(metadata),
    )
    resolver = await MunicipalityResolver.load(session)
    aggregated: dict[tuple[str, str, date], SIVIGILACanonical] = {}
    accepted = rejected = row_number = 0
    try:
        async for page in client.paginate(
            profile.dataset_id,
            query=query,
            page_size=2_000,
            max_records=request.max_records,
        ):
            writer.append_page(page)
            for row in page:
                row_number += 1
                try:
                    item = _canonicalize_territorial_row(profile, resolver, row)
                    key = (item.municipality_code, item.disease, item.week_start)
                    current = aggregated.get(key)
                    if current is None:
                        aggregated[key] = item
                    else:
                        aggregated[key] = replace(current, cases=current.cases + item.cases)
                    accepted += 1
                except CanonicalValidationError as exc:
                    rejected += 1
                    await add_quarantine(session, run, row_number, row, exc)
        artifact = writer.finalize(
            extra={
                "adapter": "territorial_sivigila",
                "dataset_id": profile.dataset_id,
                "year_from": year_from,
                "year_to": year_to,
                "row_kind": profile.kind,
                "snapshot_policy": "municipality/week aggregates only",
            }
        )
    except Exception:
        writer.abort()
        raise
    await upsert_sivigila_batch(session, run, resolver, list(aggregated.values()))
    return SyncOutcome(
        artifact=artifact,
        accepted=accepted,
        rejected=rejected,
        canonical_rows=len(aggregated),
        details={
            "adapter": "territorial_sivigila",
            "dataset_id": profile.dataset_id,
            "year_from": year_from,
            "year_to": year_to,
            "territory_source": profile.source_id,
            "extends_beyond_2024": profile.year_to >= 2025,
        },
    )


async def _sync_territorial_sivigila(
    session: AsyncSession,
    run: IngestionRun,
    source: DataSource,
    request: SourceSyncRequest,
    settings: Settings,
    http_client: httpx.AsyncClient,
) -> SyncOutcome:
    if source.id == FEDERATION_SOURCE_ID:
        members = list(territorial_profiles())
        totals = {
            "accepted": 0,
            "rejected": 0,
            "canonical_rows": 0,
            "members": [],
        }
        # Synthetic writer for federation rollup.
        writer = _writer(
            settings,
            source,
            run,
            {"federation": True, "members": [item.source_id for item in members]},
            {"name": source.name},
        )
        try:
            for profile in members:
                member_source = await session.get(DataSource, profile.source_id)
                if member_source is None:
                    raise DomainError(
                        "source_not_found",
                        (
                            f"Falta la fuente miembro {profile.source_id}; "
                            "ejecute seed del catálogo oficial antes de sincronizar "
                            "la federación territorial."
                        ),
                        409,
                    )
                # Persist under the member source for lineage, but keep the
                # federation run for operational rollup when called as federation.
                member_run = IngestionRun(
                    source_id=profile.source_id,
                    status=PipelineStatus.RUNNING.value,
                    started_at=datetime.now(UTC),
                    provenance={
                        "kind": "territorial_federation_member",
                        "federation_parent": FEDERATION_SOURCE_ID,
                        "federation_run_id": run.id,
                        "request": (run.provenance or {}).get("request", {}),
                    },
                )
                session.add(member_run)
                await session.flush()
                try:
                    outcome = await _sync_territorial_profile(
                        session,
                        member_run,
                        member_source,
                        profile,
                        request,
                        settings,
                        http_client,
                    )
                    store_snapshot(session, member_run, outcome.artifact)
                    member_run.rows_read = outcome.artifact.row_count
                    member_run.rows_accepted = outcome.accepted
                    member_run.rows_rejected = outcome.rejected
                    member_run.checksum = outcome.artifact.sha256
                    member_run.quality_report = {
                        "canonical_rows": outcome.canonical_rows,
                        "details": outcome.details,
                    }
                    member_run.status = PipelineStatus.SUCCEEDED.value
                    member_run.finished_at = datetime.now(UTC)
                except Exception as exc:
                    member_run.status = PipelineStatus.FAILED.value
                    member_run.finished_at = datetime.now(UTC)
                    member_run.error_message = str(exc)[:2_000]
                    raise
                totals["accepted"] += outcome.accepted
                totals["rejected"] += outcome.rejected
                totals["canonical_rows"] += outcome.canonical_rows
                totals["members"].append(
                    {
                        "source_id": profile.source_id,
                        "dataset_id": profile.dataset_id,
                        "member_run_id": member_run.id,
                        "accepted": outcome.accepted,
                        "canonical_rows": outcome.canonical_rows,
                        "year_to": profile.year_to,
                        "snapshot_sha256": outcome.artifact.sha256,
                    }
                )
            artifact = writer.finalize(extra={"federation_members": totals["members"]})
        except Exception:
            writer.abort()
            raise
        return SyncOutcome(
            artifact=artifact,
            accepted=int(totals["accepted"]),
            rejected=int(totals["rejected"]),
            canonical_rows=int(totals["canonical_rows"]),
            details={
                "federation": True,
                "members": totals["members"],
                "merge_policy": "prefer_newer_epidemiological_year",
            },
        )

    profile = profile_by_source_id(source.id)
    if profile is None:
        raise DomainError(
            "source_processor_unavailable",
            "Perfil territorial SIVIGILA no registrado",
            409,
        )
    return await _sync_territorial_profile(
        session, run, source, profile, request, settings, http_client
    )


async def _sync_sivigila(
    session: AsyncSession,
    run: IngestionRun,
    source: DataSource,
    request: SourceSyncRequest,
    settings: Settings,
    http_client: httpx.AsyncClient,
) -> SyncOutcome:
    client = _socrata_client(source, settings, http_client)
    connector = SIVIGILAConnector(client, dataset_id=source.dataset_id)
    start_year = (request.from_date or date(2018, 1, 1)).year
    end_year = (request.to_date - timedelta(days=1)).year if request.to_date else 2022
    if start_year < 2007 or end_year > 2022:
        raise DomainError(
            "source_period_unavailable",
            "La publicación SIVIGILA verificada contiene datos hasta 2022",
            422,
        )
    query = connector.query(year_from=start_year, year_to=end_year)
    metadata = await client.fetch_metadata(connector.require_dataset_id())
    writer = _writer(settings, source, run, query.parameters(), _publication(metadata))
    resolver = await MunicipalityResolver.load(session)
    aggregated: dict[tuple[str, str, date], Any] = {}
    accepted = rejected = row_number = 0
    try:
        async for page in connector.pages(
            query,
            max_records=request.max_records,
        ):
            writer.append_page(page)
            for row in page:
                row_number += 1
                try:
                    item = canonicalize_sivigila(row)
                    if item.municipality_code not in resolver.by_code:
                        raise CanonicalValidationError(
                            "unknown_divipola",
                            f"DIVIPOLA no registrado: {item.municipality_code}",
                        )
                    key = (item.municipality_code, item.disease, item.week_start)
                    current = aggregated.get(key)
                    aggregated[key] = (
                        replace(current, cases=current.cases + item.cases)
                        if current is not None
                        else item
                    )
                    accepted += 1
                except CanonicalValidationError as exc:
                    rejected += 1
                    await add_quarantine(session, run, row_number, row, exc)
        artifact = writer.finalize(
            extra={
                "source_semantics": "national municipality/week aggregate, no microdata",
                "data_through_year": 2022,
                "ira_proxy": "INS event 348 IRAG",
            }
        )
    except Exception:
        writer.abort()
        raise
    await upsert_sivigila_batch(session, run, resolver, list(aggregated.values()))
    return SyncOutcome(
        artifact=artifact,
        accepted=accepted,
        rejected=rejected,
        canonical_rows=len(aggregated),
        details={
            "data_through_year": 2022,
            "stale_for_current_monitoring": True,
            "ira_is_irag_proxy": True,
            "mortality_events_excluded": [540, 580],
        },
    )


_SIVIGILA_MICRODATA_MAX_FILE_BYTES = 128 * 1024 * 1024


def _validate_sivigila_microdata_selection(event_codes: list[int] | None) -> list:
    try:
        contracts = sivigila_2024_event_files(event_codes)
    except ValueError as exc:
        raise DomainError("source_event_unavailable", str(exc), 422) from exc
    selected = {contract.event_code for contract in contracts}
    canonical_groups: dict[str, set[int]] = {}
    for contract in SIVIGILA_2024_EVENT_FILES.values():
        if contract.canonical_eligible:
            canonical_groups.setdefault(contract.disease, set()).add(contract.event_code)
    for disease, complete_group in canonical_groups.items():
        requested_group = selected & complete_group
        if requested_group and requested_group != complete_group:
            raise DomainError(
                "incomplete_event_group",
                (
                    f"La sincronizacion de {disease} debe incluir el grupo completo "
                    f"{sorted(complete_group)} para no sobrescribir un total parcial"
                ),
                422,
            )
    return contracts


async def _download_sivigila_microdata_workbook(
    http_client: httpx.AsyncClient,
    source_url: str,
) -> tuple[Any, dict[str, Any]]:
    spool = tempfile.SpooledTemporaryFile(max_size=16 * 1024 * 1024, mode="w+b")
    digest = hashlib.sha256()
    content_bytes = 0
    try:
        async with http_client.stream(
            "GET",
            source_url,
            headers={
                "Accept": (
                    "application/vnd.openxmlformats-officedocument."
                    "spreadsheetml.sheet, application/octet-stream"
                ),
                "User-Agent": "PRORA/1.0 (+public-health-research)",
            },
        ) as response:
            response.raise_for_status()
            declared_length = response.headers.get("content-length")
            if declared_length and int(declared_length) > _SIVIGILA_MICRODATA_MAX_FILE_BYTES:
                raise DomainError(
                    "source_file_too_large",
                    "El XLSX SIVIGILA supera el limite operativo de 128 MB",
                    413,
                )
            async for chunk in response.aiter_bytes(1024 * 1024):
                content_bytes += len(chunk)
                if content_bytes > _SIVIGILA_MICRODATA_MAX_FILE_BYTES:
                    raise DomainError(
                        "source_file_too_large",
                        "El XLSX SIVIGILA supera el limite operativo de 128 MB",
                        413,
                    )
                digest.update(chunk)
                spool.write(chunk)
            publication = {
                "content_bytes": content_bytes,
                "raw_file_sha256": digest.hexdigest(),
                "etag": response.headers.get("etag"),
                "last_modified": response.headers.get("last-modified"),
                "content_type": response.headers.get("content-type"),
            }
        spool.seek(0)
        if spool.read(4) != b"PK\x03\x04":
            raise DomainError(
                "source_contract_mismatch",
                "La publicacion SIVIGILA no es un XLSX valido",
                409,
            )
        spool.seek(0)
        return spool, publication
    except Exception:
        spool.close()
        raise


async def _sync_sivigila_microdata_2024(
    session: AsyncSession,
    run: IngestionRun,
    source: DataSource,
    request: SourceSyncRequest,
    settings: Settings,
    http_client: httpx.AsyncClient,
) -> SyncOutcome:
    if source.endpoint != SIVIGILA_MICRODATA_DISCOVERY_URL:
        raise DomainError(
            "source_contract_mismatch",
            "El catalogo SIVIGILA no coincide con la biblioteca SharePoint verificada",
            409,
        )
    if request.max_records is not None:
        raise DomainError(
            "partial_microdata_sync_forbidden",
            "SIVIGILA 2024 no permite cortes por max_records porque alterarian los totales",
            422,
        )
    if request.from_date and request.from_date < date(2024, 1, 1):
        raise DomainError(
            "source_period_unavailable", "Esta fuente contiene solo la vigencia 2024", 422
        )
    if request.to_date and request.to_date > date(2025, 1, 1):
        raise DomainError(
            "source_period_unavailable", "Esta fuente contiene solo la vigencia 2024", 422
        )
    contracts = _validate_sivigila_microdata_selection(request.event_codes)
    resolver = await MunicipalityResolver.load(session)
    if not resolver.by_code:
        raise DomainError(
            "divipola_required",
            "Sincronice DANE DIVIPOLA antes de interpretar SIVIGILA 2024",
            409,
        )

    writer = _writer(
        settings,
        source,
        run,
        {
            "year": 2024,
            "event_codes": [contract.event_code for contract in contracts],
            "snapshot_semantics": "sanitised municipality/week aggregates only",
        },
        {
            "publisher": "Instituto Nacional de Salud - INS",
            "discovery_url": SIVIGILA_MICRODATA_DISCOVERY_URL,
        },
    )
    canonical: dict[tuple[str, str, date], SIVIGILACanonical] = {}
    files: list[dict[str, Any]] = []
    schemas: list[dict[str, Any]] = []
    source_rows_seen = source_rows_accepted = source_rows_rejected = 0
    aggregate_rows = unknown_divipola = context_rows = 0
    try:
        for contract in contracts:
            spool, publication = await _download_sivigila_microdata_workbook(
                http_client, contract.url
            )
            try:
                parsed: ParsedSIVIGILAMicrodata = await anyio.to_thread.run_sync(
                    partial(parse_sivigila_2024_workbook, spool, contract)
                )
            finally:
                # Raw row-level bytes are never published to the snapshot store.
                spool.close()
            source_rows_seen += parsed.rows_seen
            source_rows_accepted += parsed.rows_accepted
            source_rows_rejected += parsed.rows_rejected
            aggregate_rows += len(parsed.records)
            schemas.append(parsed.schema_descriptor)
            files.append(
                {
                    "event_code": contract.event_code,
                    "event_name": contract.event_name,
                    "url": contract.url,
                    "measure": contract.measure.value,
                    "canonical_eligible": contract.canonical_eligible,
                    "source_rows_seen": parsed.rows_seen,
                    "source_rows_accepted": parsed.rows_accepted,
                    "source_rows_rejected": parsed.rows_rejected,
                    "duplicate_rows": parsed.duplicate_rows,
                    **publication,
                }
            )
            safe_rows = [record.snapshot_payload() for record in parsed.records]
            writer.append_page(safe_rows)
            for rejection in parsed.rejections:
                await add_quarantine(
                    session,
                    run,
                    rejection.row_number,
                    rejection.safe_payload,
                    CanonicalValidationError(rejection.reason_code, rejection.reason),
                )
            for record in parsed.records:
                if not record.canonical_eligible:
                    context_rows += 1
                    continue
                if record.municipality_code not in resolver.by_code:
                    unknown_divipola += 1
                    await add_quarantine(
                        session,
                        run,
                        0,
                        record.snapshot_payload(),
                        CanonicalValidationError(
                            "unknown_divipola",
                            f"DIVIPOLA no registrado: {record.municipality_code}",
                        ),
                    )
                    continue
                key = (record.municipality_code, record.disease, record.week_start)
                current = canonical.get(key)
                if current is None:
                    canonical[key] = SIVIGILACanonical(
                        municipality_code=record.municipality_code,
                        disease=record.disease,
                        week_start=record.week_start,
                        epidemiological_week=record.epidemiological_week,
                        epidemiological_year=record.epidemiological_year,
                        cases=record.value,
                        raw_record_sha256=hashlib.sha256(
                            repr(sorted(record.snapshot_payload().items())).encode("utf-8")
                        ).hexdigest(),
                    )
                else:
                    canonical[key] = replace(current, cases=current.cases + record.value)
        artifact = writer.finalize(
            extra={
                "adapter_version": SIVIGILA_MICRODATA_ADAPTER_VERSION,
                "data_through_year": 2024,
                "source_rows_seen": source_rows_seen,
                "source_rows_accepted": source_rows_accepted,
                "source_rows_rejected": source_rows_rejected,
                "sanitised_aggregate_rows": aggregate_rows,
                "canonical_rows": len(canonical),
                "context_only_rows": context_rows,
                "unknown_divipola_aggregates": unknown_divipola,
                "source_files": files,
                "parser_contracts": schemas,
                "privacy": {
                    "raw_workbooks_persisted": False,
                    "raw_rows_persisted": False,
                    "snapshot_contains_aggregates_only": True,
                    "aggregation": "event/municipality/epidemiological-week",
                },
                "ira_contract": {
                    "canonical_proxy_event": 348,
                    "context_only_events": [345, 995],
                    "reason": (
                        "No se mezclan vigilancia centinela, IRAG inusitado y "
                        "atenciones colectivas porque sus unidades no son equivalentes"
                    ),
                },
            }
        )
    except Exception:
        writer.abort()
        raise
    await upsert_sivigila_batch(session, run, resolver, list(canonical.values()))
    return SyncOutcome(
        artifact=artifact,
        accepted=max(0, artifact.row_count - unknown_divipola),
        rejected=unknown_divipola,
        canonical_rows=len(canonical),
        details={
            "contract_valid": True,
            "adapter_version": SIVIGILA_MICRODATA_ADAPTER_VERSION,
            "data_through_year": 2024,
            "stale_for_current_monitoring": True,
            "source_rows_seen": source_rows_seen,
            "source_rows_accepted": source_rows_accepted,
            "source_rows_rejected": source_rows_rejected,
            "raw_workbooks_persisted": False,
            "snapshot_contains_aggregates_only": True,
            "context_only_aggregate_rows": context_rows,
            "unknown_divipola_aggregates": unknown_divipola,
            "ira_canonical_proxy_event": 348,
            "ira_context_only_events": [345, 995],
        },
        cursor="2024-final",
    )


async def _ensure_irca_column(session: AsyncSession) -> None:
    """SQLite create_all does not add columns; keep local demos usable."""

    bind = session.get_bind()
    if bind is None or bind.dialect.name != "sqlite":
        return
    rows = await session.execute(sa_text("PRAGMA table_info(socioeconomic_indicators)"))
    columns = {str(row[1]) for row in rows}
    if "irca_index" not in columns:
        await session.execute(
            sa_text("ALTER TABLE socioeconomic_indicators ADD COLUMN irca_index FLOAT")
        )


async def _sync_irca(
    session: AsyncSession,
    run: IngestionRun,
    source: DataSource,
    request: SourceSyncRequest,
    settings: Settings,
    http_client: httpx.AsyncClient,
) -> SyncOutcome:
    await _ensure_irca_column(session)
    client = _socrata_client(source, settings, http_client)
    year_from = (request.from_date or date(2018, 1, 1)).year
    year_to = (request.to_date - timedelta(days=1)).year if request.to_date else 2024
    year_from = max(2013, year_from)
    year_to = min(2024, year_to)
    query = SafeQuery(
        filters=(
            Filter("a_o", Operator.GTE, str(year_from)),
            Filter("a_o", Operator.LTE, str(year_to)),
        ),
        order_by=(("a_o", "ASC"), ("municipiocodigo", "ASC")),
    )
    metadata = await client.fetch_metadata(source.dataset_id or "nxt2-39c3")
    writer = _writer(settings, source, run, query.parameters(), _publication(metadata))
    resolver = await MunicipalityResolver.load(session)
    accepted = rejected = row_number = 0
    batch: list[tuple[str, int, float]] = []
    try:
        async for page in client.paginate(
            source.dataset_id or "nxt2-39c3",
            query=query,
            page_size=2_000,
            max_records=request.max_records,
        ):
            writer.append_page(page)
            for row in page:
                row_number += 1
                code = str(row.get("municipiocodigo") or "").strip().zfill(5)
                if not code.isdigit() or code in {"00000"} or "#" in str(row.get("municipiocodigo") or ""):
                    rejected += 1
                    await add_quarantine(
                        session,
                        run,
                        row_number,
                        row,
                        CanonicalValidationError(
                            "non_municipal_irca_row",
                            "Fila IRCA departamental/agregada omitida",
                        ),
                    )
                    continue
                if code not in resolver.by_code:
                    rejected += 1
                    await add_quarantine(
                        session,
                        run,
                        row_number,
                        row,
                        CanonicalValidationError("unknown_divipola", f"DIVIPOLA {code}"),
                    )
                    continue
                try:
                    year = int(str(row["a_o"]).split(".", 1)[0])
                    irca = float(row["irca"])
                except (KeyError, TypeError, ValueError) as exc:
                    rejected += 1
                    await add_quarantine(
                        session,
                        run,
                        row_number,
                        row,
                        CanonicalValidationError("invalid_irca", str(exc)),
                    )
                    continue
                if year < year_from or year > year_to or irca < 0 or irca > 100:
                    rejected += 1
                    continue
                batch.append((code, year, irca))
                accepted += 1
        artifact = writer.finalize(extra={"adapter": "irca_municipal", "year_from": year_from, "year_to": year_to})
    except Exception:
        writer.abort()
        raise
    await upsert_irca_batch(session, run, batch)
    return SyncOutcome(
        artifact=artifact,
        accepted=accepted,
        rejected=rejected,
        canonical_rows=len(batch),
        details={"adapter": "irca_municipal", "year_from": year_from, "year_to": year_to},
    )


async def _sync_pai_territorial_socrata(
    session: AsyncSession,
    run: IngestionRun,
    source: DataSource,
    request: SourceSyncRequest,
    settings: Settings,
    http_client: httpx.AsyncClient,
) -> SyncOutcome:
    client = _socrata_client(source, settings, http_client)
    year_from = (request.from_date or date(2022, 1, 1)).year
    year_to = (request.to_date - timedelta(days=1)).year if request.to_date else 2022
    query = SafeQuery(
        filters=(
            Filter("a_o", Operator.GTE, str(year_from)),
            Filter("a_o", Operator.LTE, str(year_to)),
        ),
        order_by=(("a_o", "ASC"), ("mes", "ASC")),
    )
    metadata = await client.fetch_metadata(source.dataset_id or "uw8e-gzpp")
    writer = _writer(settings, source, run, query.parameters(), _publication(metadata))
    resolver = await MunicipalityResolver.load(session)
    records: list[PAIMunicipalRecord] = []
    accepted = rejected = row_number = 0
    try:
        async for page in client.paginate(
            source.dataset_id or "uw8e-gzpp",
            query=query,
            page_size=2_000,
            max_records=request.max_records,
        ):
            writer.append_page(page)
            for row in page:
                row_number += 1
                code = str(row.get("codigo_municipio") or "").strip().zfill(5)
                month_name = str(row.get("mes") or "").strip().upper()
                month = _MONTH_NAME_TO_NUMBER.get(month_name)
                biologic = str(row.get("biologico") or "").strip()
                if code not in resolver.by_code or month is None or not biologic:
                    rejected += 1
                    await add_quarantine(
                        session,
                        run,
                        row_number,
                        row,
                        CanonicalValidationError(
                            "invalid_pai_territorial_row",
                            "Municipio/mes/biológico inválidos",
                        ),
                    )
                    continue
                try:
                    year = int(str(row["a_o"]).split(".", 1)[0])
                    coverage = float(str(row.get("cobertura") or "0").replace(",", "."))
                    doses_raw = row.get("dosis_aplicadas")
                    doses = int(float(doses_raw)) if doses_raw not in (None, "") else None
                except (KeyError, TypeError, ValueError) as exc:
                    rejected += 1
                    await add_quarantine(
                        session,
                        run,
                        row_number,
                        row,
                        CanonicalValidationError("invalid_pai_values", str(exc)),
                    )
                    continue
                vaccine = biologic.upper().replace(" ", "_")[:100]
                records.append(
                    PAIMunicipalRecord(
                        municipality_code=code,
                        year=year,
                        month=month,
                        vaccine=vaccine,
                        source_label=biologic,
                        coverage_pct=coverage,
                        doses_applied=doses,
                        sheet="socrata",
                        row_number=row_number,
                    )
                )
                accepted += 1
        artifact = writer.finalize(extra={"adapter": "pai_territorial_socrata"})
    except Exception:
        writer.abort()
        raise
    await upsert_municipal_pai_batch(session, run, records)
    return SyncOutcome(
        artifact=artifact,
        accepted=accepted,
        rejected=rejected,
        canonical_rows=len(records),
        details={"adapter": "pai_territorial_socrata", "year_from": year_from, "year_to": year_to},
    )


async def _sync_pai(
    session: AsyncSession,
    run: IngestionRun,
    source: DataSource,
    request: SourceSyncRequest,
    settings: Settings,
    http_client: httpx.AsyncClient,
) -> SyncOutcome:
    client = _socrata_client(source, settings, http_client)
    connector = PAIConnector(client, dataset_id=source.dataset_id)
    start_year = (request.from_date or date(2019, 1, 1)).year
    end_year = (request.to_date - timedelta(days=1)).year if request.to_date else 2022
    if start_year < 2019 or end_year > 2022:
        raise DomainError(
            "source_period_unavailable",
            "La publicación PAI departamental verificada contiene 2019–2022",
            422,
        )
    query = connector.query(year_from=start_year, year_to=end_year)
    metadata = await client.fetch_metadata(connector.require_dataset_id())
    writer = _writer(settings, source, run, query.parameters(), _publication(metadata))
    items: dict[tuple[str, int, str], Any] = {}
    accepted = rejected = duplicates = row_number = 0
    try:
        async for page in connector.pages(query, max_records=request.max_records):
            writer.append_page(page)
            for row in page:
                row_number += 1
                try:
                    item = canonicalize_pai(row)
                    key = (item.department_code, item.year, item.vaccine)
                    if key in items:
                        duplicates += 1
                        rejected += 1
                        await add_quarantine(
                            session,
                            run,
                            row_number,
                            row,
                            CanonicalValidationError(
                                "canonical_key_collision",
                                "Dos rótulos PAI colapsan a la misma clave canónica; "
                                "no se sobrescribe.",
                            ),
                        )
                        continue
                    items[key] = item
                    accepted += 1
                except CanonicalValidationError as exc:
                    rejected += 1
                    await add_quarantine(session, run, row_number, row, exc)
        artifact = writer.finalize(
            extra={"territorial_resolution": "department", "temporal_resolution": "year"}
        )
    except Exception:
        writer.abort()
        raise
    for item in items.values():
        await upsert_pai(session, run, item)
    return SyncOutcome(
        artifact=artifact,
        accepted=accepted,
        rejected=rejected,
        canonical_rows=len(items),
        details={
            "territorial_resolution": "department",
            "municipal_allocation_performed": False,
            "canonical_label_collisions": duplicates,
        },
    )


async def _sync_pai_file(
    session: AsyncSession,
    run: IngestionRun,
    source: DataSource,
    request: SourceSyncRequest,
    settings: Settings,
    http_client: httpx.AsyncClient,
    contract: PAIFileContract,
) -> SyncOutcome:
    if source.endpoint != contract.url:
        raise DomainError(
            "source_contract_mismatch",
            "El endpoint configurado no coincide con el contrato PAI aprobado",
            409,
        )
    start_year: int | None = None
    end_year: int | None = None
    months: set[int] | None = None
    if contract.kind == "history":
        start_year = (request.from_date or date(1998, 1, 1)).year
        end_year = (request.to_date - timedelta(days=1)).year if request.to_date else 2025
        if start_year < 1998 or end_year > 2025:
            raise DomainError(
                "source_period_unavailable",
                "El archivo municipal histórico PAI contiene 1998–2025",
                422,
            )
    else:
        start = request.from_date or date(2026, 1, 1)
        end = request.to_date or date(2026, 3, 1)
        months = {
            month
            for month in (1, 2)
            if date(2026, month, 1) < end
            and (date(2026, month + 1, 1) if month < 12 else date(2027, 1, 1)) > start
        }
        if not months:
            raise DomainError(
                "source_period_unavailable",
                "La publicación PAI 2026 verificada solo contiene cortes de enero y febrero",
                422,
            )

    writer: RawFileSnapshotWriter | None = None
    try:
        async with http_client.stream(
            "GET",
            contract.url,
            headers={
                "Accept": "application/zip, application/octet-stream",
                "User-Agent": "PRORA/1.0 (+public-health-research)",
            },
        ) as response:
            response.raise_for_status()
            writer = RawFileSnapshotWriter(
                root=settings.raw_snapshot_dir,
                source_id=source.id,
                run_id=run.id,
                source_url=contract.url,
                media_type="application/zip",
                query=request.model_dump(mode="json"),
                publication={
                    "publisher": "Ministerio de Salud y Protección Social",
                    "etag": response.headers.get("etag"),
                    "last_modified": response.headers.get("last-modified"),
                    "content_length": response.headers.get("content-length"),
                },
            )
            async for chunk in response.aiter_bytes(1024 * 1024):
                writer.append_chunk(chunk)

        resolver = await MunicipalityResolver.load(session)
        if not resolver.by_code:
            raise DomainError(
                "divipola_required",
                "Sincronice DANE DIVIPOLA antes de interpretar el archivo PAI municipal",
                409,
            )
        parsed = await anyio.to_thread.run_sync(
            partial(
                parse_pai_publication,
                writer.staging_path(),
                contract,
                start_year=start_year,
                end_year=end_year,
                months=months,
                official_municipalities={
                    code: municipality.name for code, municipality in resolver.by_code.items()
                },
            )
        )
        artifact = writer.finalize(
            row_count=parsed.rows_seen,
            schema_descriptor=parsed.schema_descriptor,
            extra={
                "adapter_version": PAI_ADAPTER_VERSION,
                "contract_valid": parsed.contract_valid,
                "workbook_sha256": parsed.workbook_sha256,
                "excluded_nonmunicipal_rows": parsed.skipped_rows,
                "canonical_measure_rows": len(parsed.records),
            },
        )
    except Exception:
        if writer is not None:
            writer.abort()
        raise

    for rejection in parsed.rejections:
        await add_quarantine(
            session,
            run,
            rejection.row_number,
            rejection.payload,
            CanonicalValidationError(rejection.reason_code, rejection.reason),
        )
    if parsed.contract_valid:
        await upsert_municipal_pai_batch(session, run, parsed.records)
    accepted_rows = len({(record.sheet, record.row_number) for record in parsed.records})
    rejected_rows = len(
        {
            (str(rejection.payload.get("sheet", "file")), rejection.row_number)
            for rejection in parsed.rejections
        }
    )
    return SyncOutcome(
        artifact=artifact,
        accepted=accepted_rows,
        rejected=rejected_rows,
        canonical_rows=len(parsed.records) if parsed.contract_valid else 0,
        details={
            "contract_valid": parsed.contract_valid,
            "adapter_version": PAI_ADAPTER_VERSION,
            "territory_name_aliases": len(
                parsed.schema_descriptor.get("territory_name_aliases", [])
            ),
            "canonical_measure_rows": len(parsed.records),
            "excluded_nonmunicipal_rows": parsed.skipped_rows,
            "territorial_resolution": "municipality",
            "temporal_resolution": (
                "year" if contract.kind == "history" else "cumulative_month_cutoff"
            ),
            "municipal_allocation_performed": False,
        },
    )


def _climate_window(source: DataSource, request: SourceSyncRequest) -> tuple[date, date]:
    today = datetime.now(UTC).date()
    if request.mode == "backfill":
        start = request.from_date
        end = request.to_date
    else:
        cursor = source.configuration.get("cursor")
        start = request.from_date or (
            date.fromisoformat(str(cursor)) - timedelta(days=7)
            if cursor
            else today - timedelta(days=8)
        )
        end = request.to_date or today + timedelta(days=1)
    assert start is not None and end is not None
    maximum = int(source.configuration.get("max_backfill_days", 366))
    if (end - start).days > maximum:
        raise DomainError(
            "backfill_window_too_large",
            f"La ventana máxima para esta fuente es {maximum} días",
            422,
        )
    return start, end


async def _sync_climate(
    session: AsyncSession,
    run: IngestionRun,
    source: DataSource,
    request: SourceSyncRequest,
    settings: Settings,
    http_client: httpx.AsyncClient,
) -> SyncOutcome:
    start, end = _climate_window(source, request)
    metric = str(source.configuration["metric"])
    aggregate = Aggregate.SUM if metric == "precipitation" else Aggregate.AVG
    client = _socrata_client(source, settings, http_client)
    connector = IDEAMClimateConnector(client, dataset_id=source.dataset_id)
    query = connector.daily_station_query(
        observed_from=datetime.combine(start, time.min),
        observed_to=datetime.combine(end, time.min),
        aggregation=aggregate,
    )
    metadata = await client.fetch_metadata(connector.require_dataset_id())
    writer = _writer(settings, source, run, query.parameters(), _publication(metadata))
    resolver = await MunicipalityResolver.load(session)
    buckets: dict[tuple[str, date], ClimateBucket] = {}
    accepted = rejected = row_number = 0
    try:
        async for page in connector.pages(query, max_records=request.max_records):
            writer.append_page(page)
            for row in page:
                row_number += 1
                try:
                    code, week, station, value, count = climate_week_key(row, resolver)
                    buckets.setdefault((code, week), ClimateBucket()).add(station, value, count)
                    accepted += 1
                except CanonicalValidationError as exc:
                    rejected += 1
                    await add_quarantine(session, run, row_number, row, exc)
        artifact = writer.finalize(
            extra={
                "metric": metric,
                "remote_aggregation": "station/day",
                "local_aggregation": "municipality/Sunday-week",
            }
        )
    except Exception:
        writer.abort()
        raise
    await upsert_climate_buckets(session, run, buckets, metric, artifact.sha256)
    return SyncOutcome(
        artifact=artifact,
        accepted=accepted,
        rejected=rejected,
        canonical_rows=len(buckets),
        details={
            "metric": metric,
            "requested_period": {"from": start.isoformat(), "to_exclusive": end.isoformat()},
            "week_definition": "Sunday-Saturday",
        },
        cursor=end.isoformat(),
    )


async def _sync_stations(
    session: AsyncSession,
    run: IngestionRun,
    source: DataSource,
    settings: Settings,
    http_client: httpx.AsyncClient,
) -> SyncOutcome:
    client = _socrata_client(source, settings, http_client)
    connector = IDEAMStationsConnector(client, dataset_id=source.dataset_id)
    query = connector.query()
    metadata = await client.fetch_metadata(connector.require_dataset_id())
    writer = _writer(settings, source, run, query.parameters(), _publication(metadata))
    resolver = await MunicipalityResolver.load(session)
    accepted = rejected = unresolved = row_number = duplicates = 0
    # The catalog currently contains repeated station codes. Pagination is
    # ordered by code and Socrata row id, so keeping the last row is a stable,
    # auditable policy (highest internal :id) rather than a database accident.
    latest_by_code: dict[str, tuple[int, dict[str, Any]]] = {}
    try:
        async for page in connector.pages(query):
            writer.append_page(page)
            for row in page:
                row_number += 1
                code = str(row.get("codigo") or "").strip()
                if not code:
                    rejected += 1
                    await add_quarantine(
                        session,
                        run,
                        row_number,
                        row,
                        CanonicalValidationError(
                            "missing_station_identity", "Código de estación requerido"
                        ),
                    )
                    continue
                duplicates += int(code in latest_by_code)
                latest_by_code[code] = (row_number, row)
        artifact = writer.finalize(
            extra={
                "duplicate_station_rows": duplicates,
                "duplicate_resolution": "highest Socrata :id per station code",
            }
        )
        for original_row_number, row in latest_by_code.values():
            try:
                resolved = await upsert_station(session, run, resolver, row)
                accepted += 1
                unresolved += int(not resolved)
            except CanonicalValidationError as exc:
                rejected += 1
                await add_quarantine(session, run, original_row_number, row, exc)
    except Exception:
        writer.abort()
        raise
    return SyncOutcome(
        artifact=artifact,
        accepted=accepted,
        rejected=rejected,
        canonical_rows=accepted,
        details={
            "stations_without_divipola_match": unresolved,
            "duplicate_station_rows": duplicates,
            "duplicate_resolution": "highest Socrata :id per station code",
        },
    )


async def _sync_divipola(
    session: AsyncSession,
    run: IngestionRun,
    source: DataSource,
    settings: Settings,
    http_client: httpx.AsyncClient,
) -> SyncOutcome:
    rows = await DIVIPOLAConnector(
        http_client, endpoint=source.endpoint or ""
    ).fetch_municipalities()
    writer = _writer(
        settings,
        source,
        run,
        {
            "where": "1=1",
            "returnIdsOnly": True,
            "returnGeometry": True,
            "maxAllowableOffset": 1000,
            "spatial_reference": "EPSG:3857",
        },
        {"publisher": "DANE", "layer": "DIVIPOLA MGN 2025 / Municipio 317"},
    )
    writer.append_page(rows)
    accepted = rejected = 0
    for row_number, row in enumerate(rows, start=1):
        code = str(row.get("MPIO_CDPMP") or "").zfill(5)
        department_code = str(row.get("DPTO_CCDGO") or code[:2]).zfill(2)
        name = str(row.get("MPIO_CNMBRE") or "").strip()
        department_name = str(row.get("DPTO_CNMBRE") or "").strip()
        if len(code) != 5 or not code.isdigit() or not name or not department_name:
            rejected += 1
            await add_quarantine(
                session,
                run,
                row_number,
                row,
                CanonicalValidationError("invalid_divipola", "Código/nombres incompletos"),
            )
            continue
        await session.merge(
            Municipality(
                code=code,
                name=name,
                department_code=department_code,
                department_name=department_name,
                latitude=row.get("_latitude"),
                longitude=row.get("_longitude"),
                source_vintage=f"DANE DIVIPOLA {row.get('MPIO_NANO') or 2025}",
            )
        )
        accepted += 1
    artifact = writer.finalize()
    return SyncOutcome(
        artifact,
        accepted,
        rejected,
        accepted,
        {"marker_coordinates": "simplified EPSG:3857 polygon center converted to WGS84"},
    )


async def _sync_cnpv(
    session: AsyncSession,
    run: IngestionRun,
    source: DataSource,
    settings: Settings,
    http_client: httpx.AsyncClient,
) -> SyncOutcome:
    class_endpoint = str(source.configuration.get("class_composition_endpoint") or "")
    connector = DANECNPVConnector(
        http_client,
        endpoint=source.endpoint or "",
        **({"class_endpoint": class_endpoint} if class_endpoint else {}),
    )
    rows = await connector.fetch_municipal_indicators()
    class_rows = await connector.fetch_class_indicators()
    municipality_snapshot_rows = [
        {**row, "_source_layer": "CNPV 2018 Municipios Integrados / 800"} for row in rows
    ]
    class_snapshot_rows = [
        {**row, "_source_layer": "CNPV 2018 Clases Integradas / 801"} for row in class_rows
    ]
    writer = _writer(
        settings,
        source,
        run,
        {
            "where": "OBJECTID > 0",
            "returnGeometry": False,
            "vintage": 2018,
            "layers": [800, 801],
        },
        {
            "publisher": "DANE",
            "layers": [
                "CNPV 2018 Municipios Integrados / 800",
                "CNPV 2018 Clases Integradas / 801",
            ],
        },
    )
    writer.append_page(municipality_snapshot_rows)
    writer.append_page(class_snapshot_rows)
    resolver = await MunicipalityResolver.load(session)
    accepted = rejected = class_accepted = municipal_accepted = 0
    class_population: dict[str, dict[str, float]] = {}
    class_keys: set[tuple[str, str]] = set()
    for row_number, row in enumerate(class_rows, start=len(rows) + 1):
        try:
            item = canonicalize_cnpv_class(row)
            if item.municipality_code not in resolver.by_code:
                raise CanonicalValidationError(
                    "unknown_divipola",
                    f"DIVIPOLA no registrado: {item.municipality_code}",
                )
            key = (item.municipality_code, item.class_code)
            if key in class_keys:
                raise CanonicalValidationError(
                    "duplicate_cnpv_class",
                    f"Clase CNPV duplicada para {item.municipality_code}/{item.class_code}",
                )
            class_keys.add(key)
            class_population.setdefault(item.municipality_code, {})[item.class_code] = (
                item.population
            )
            class_accepted += 1
            accepted += 1
        except CanonicalValidationError as exc:
            rejected += 1
            await add_quarantine(session, run, row_number, row, exc)
    for row_number, row in enumerate(rows, start=1):
        try:
            code = str(row.get("MPIO_CDPMP") or "").strip().zfill(5)
            await upsert_cnpv(
                session,
                run,
                resolver,
                row,
                class_population=class_population.get(code),
            )
            municipal_accepted += 1
            accepted += 1
        except CanonicalValidationError as exc:
            rejected += 1
            await add_quarantine(session, run, row_number, row, exc)
    artifact = writer.finalize(
        extra={
            "formulas": {
                "water_access_pct": "STP19_ACU1/(STP19_ACU1+STP19_ACU2)*100",
                "sewer_access_pct": "STP19_ALC1/(STP19_ALC1+STP19_ALC2)*100",
                "urban_population_pct": (
                    "layer801.CLAS_CCDGO=1 STP27_PERS / sum(classes 1,2,3) * 100"
                ),
                "rural_population_pct": (
                    "layer801.CLAS_CCDGO in (2,3) STP27_PERS / sum(classes 1,2,3) * 100"
                ),
            }
        }
    )
    municipalities_with_composition = len(class_population)
    return SyncOutcome(
        artifact,
        accepted,
        rejected,
        municipal_accepted,
        {
            "vintage": 2018,
            "municipal_rows_accepted": municipal_accepted,
            "class_rows_accepted": class_accepted,
            "municipalities_with_class_composition": municipalities_with_composition,
            "municipalities_without_class_composition": max(
                0, municipal_accepted - municipalities_with_composition
            ),
            "urban_rural_policy": (
                "urban=class 1 cabecera; rural=class 2 centro poblado + "
                "class 3 area resto municipal"
            ),
        },
    )


async def recent_runs(session: AsyncSession, limit: int = 50) -> list[IngestionRun]:
    statement = select(IngestionRun).order_by(IngestionRun.started_at.desc()).limit(limit)
    return list((await session.scalars(statement)).all())
