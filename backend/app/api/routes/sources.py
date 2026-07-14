from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from typing import Annotated
from uuid import uuid4

import anyio
from fastapi import APIRouter, Depends, File, Form, Query, Request, Response, UploadFile, status
from sqlalchemy import select

from app.api.dependencies import SessionDep, require_roles
from app.core.errors import DomainError
from app.models.entities import User, UserRole
from app.models.epidemiology import DataSource, IngestionRun, PipelineStatus, RawSnapshot
from app.schemas.sources import (
    DatasetType,
    DataSourceResponse,
    DiseaseDataCoverage,
    IngestionRunResponse,
    SnapshotManifestResponse,
    SourceSyncRequest,
    StoredDatasetInventory,
)
from app.services.data_inventory import stored_data_inventory
from app.services.disease_coverage import disease_data_coverage
from app.services.source_catalog import seed_source_catalog
from app.services.source_sync import recent_runs, schedule_source_sync

router = APIRouter(prefix="/sources", tags=["data sources"])
Operator = Annotated[User, Depends(require_roles(UserRole.ANALYST, UserRole.ADMIN))]


@router.get("", response_model=list[DataSourceResponse])
async def list_sources(session: SessionDep) -> list[DataSource]:
    sources = list(
        (
            await session.scalars(
                select(DataSource).order_by(DataSource.institution, DataSource.name)
            )
        ).all()
    )
    if not sources:
        sources = await seed_source_catalog(session)
    return sources


@router.get("/runs", response_model=list[IngestionRunResponse])
async def list_ingestion_runs(
    session: SessionDep,
    limit: int = Query(default=50, ge=1, le=200),
) -> list:
    return await recent_runs(session, limit)


@router.get("/inventory", response_model=list[StoredDatasetInventory])
async def list_stored_data_inventory(session: SessionDep) -> list[StoredDatasetInventory]:
    sources = list(
        (
            await session.scalars(
                select(DataSource).order_by(DataSource.institution, DataSource.name)
            )
        ).all()
    )
    if not sources:
        sources = await seed_source_catalog(session)
    return await stored_data_inventory(session, sources)


@router.get("/disease-coverage", response_model=list[DiseaseDataCoverage])
async def list_disease_data_coverage(session: SessionDep) -> list[DiseaseDataCoverage]:
    """Separate observed history, trained models and current operational output."""

    return await disease_data_coverage(session)


@router.get(
    "/runs/{run_id}/manifest",
    response_model=SnapshotManifestResponse,
)
async def get_snapshot_manifest(run_id: str, session: SessionDep) -> SnapshotManifestResponse:
    snapshot = await session.scalar(
        select(RawSnapshot).where(RawSnapshot.ingestion_run_id == run_id)
    )
    if snapshot is None:
        raise DomainError(
            "snapshot_not_found",
            "La ejecución no tiene un snapshot inmutable disponible",
            404,
        )
    return SnapshotManifestResponse(
        ingestion_run_id=run_id,
        source_id=snapshot.source_id,
        object_sha256=snapshot.sha256,
        manifest=snapshot.manifest,
    )


@router.post(
    "/{source_id}/sync",
    response_model=IngestionRunResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def trigger_source_sync(
    source_id: str,
    _: Operator,
    session: SessionDep,
    payload: SourceSyncRequest | None = None,
) -> IngestionRun:
    return await schedule_source_sync(session, source_id, payload or SourceSyncRequest())


TEMPLATE_HEADERS: dict[str, str] = {
    "epidemiology": (
        "municipality_code,disease,week_start,cases,population,is_preliminary,quality_score\n"
    ),
    "climate": (
        "municipality_code,week_start,precipitation_mm,temperature_mean_c,"
        "humidity_relative_pct,quality_score\n"
    ),
    "vaccination": (
        "municipality_code,year,month,vaccine,target_population,doses_applied,coverage_pct\n"
    ),
    "deforestation": (
        "municipality_code,year,quarter,deforested_hectares,early_warning_count,"
        "has_active_warning\n"
    ),
    "socioeconomic": (
        "municipality_code,year,water_access_pct,sewer_access_pct,overcrowding_pct,nbi_pct\n"
    ),
}


@router.get("/templates/{dataset_type}", response_class=Response)
async def download_template(dataset_type: DatasetType) -> Response:
    return Response(
        TEMPLATE_HEADERS[dataset_type],
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="prora-{dataset_type}-template.csv"'
        },
    )


@router.post(
    "/{source_id}/upload",
    response_model=IngestionRunResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def upload_institutional_dataset(
    source_id: str,
    request: Request,
    _: Operator,
    session: SessionDep,
    dataset_type: Annotated[DatasetType, Form()],
    file: Annotated[UploadFile, File(description="Archivo CSV canónico sin datos personales")],
) -> IngestionRun:
    source = await session.get(DataSource, source_id)
    if source is None:
        raise DomainError("source_not_found", "La fuente solicitada no existe", 404)
    original_name = Path(file.filename or "upload.csv").name
    if Path(original_name).suffix.casefold() != ".csv":
        raise DomainError("unsupported_file_type", "La carga institucional admite CSV UTF-8", 415)

    settings = request.app.state.settings
    target = await anyio.to_thread.run_sync(
        _prepare_upload_target, settings.institutional_upload_dir
    )
    digest = sha256()
    size = 0
    maximum = settings.max_upload_mb * 1024 * 1024
    try:
        async with await anyio.open_file(target, "xb") as stream:
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > maximum:
                    raise DomainError(
                        "file_too_large",
                        f"El archivo supera el límite de {settings.max_upload_mb} MB",
                        413,
                    )
                digest.update(chunk)
                await stream.write(chunk)
    except Exception:
        await anyio.to_thread.run_sync(_remove_upload, target)
        raise
    finally:
        await file.close()

    run = IngestionRun(
        source_id=source_id,
        status=PipelineStatus.PENDING.value,
        checksum=digest.hexdigest(),
        provenance={
            "dataset_type": dataset_type,
            "upload_path": str(target),
            "original_filename": original_name,
            "content_bytes": size,
            "requested_by": _.id,
        },
    )
    session.add(run)
    await session.commit()
    await session.refresh(run)
    return run


def _prepare_upload_target(root: str) -> Path:
    upload_root = Path(root).expanduser().resolve()
    upload_root.mkdir(parents=True, exist_ok=True)
    return upload_root / f"{uuid4().hex}.csv"


def _remove_upload(path: Path) -> None:
    path.unlink(missing_ok=True)
