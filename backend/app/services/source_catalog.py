from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.epidemiology import DataSource, SourceStatus

OFFICIAL_SOURCE_CATALOG: tuple[dict, ...] = (
    {
        "id": "dane-divipola",
        "name": "DIVIPOLA municipal 2025",
        "institution": "DANE",
        "source_type": "arcgis-rest",
        "endpoint": (
            "https://geoportal.dane.gov.co/mparcgis/rest/services/Divipola/"
            "Serv_DIVIPOLA_MGN_2025/FeatureServer/317/query"
        ),
        "status": SourceStatus.ACTIVE.value,
        "refresh_cron": "0 3 1 * *",
        "configuration": {
            "coverage": "national",
            "geometry": "simplified EPSG:3857; marker converted to WGS84",
            "dataset_type": "municipalities",
            "verified_on": "2026-07-13",
            "publisher": "DANE",
        },
    },
    {
        "id": "ideam-climate",
        "name": "Datos de estaciones IDEAM y de terceros",
        "institution": "IDEAM",
        "source_type": "socrata",
        "endpoint": "https://www.datos.gov.co/resource/57sv-p2fu.json",
        "dataset_id": "57sv-p2fu",
        "status": SourceStatus.DISABLED.value,
        "refresh_cron": None,
        "configuration": {
            "coverage": "national",
            "reason": "Sustituido por publicaciones IDEAM específicas por variable.",
            "verified_on": "2026-07-13",
        },
    },
    {
        "id": "ideam-precipitation",
        "name": "Precipitación automática",
        "institution": "IDEAM",
        "source_type": "socrata",
        "endpoint": "https://www.datos.gov.co/resource/s54a-sgyg.json",
        "dataset_id": "s54a-sgyg",
        "status": SourceStatus.ACTIVE.value,
        "refresh_cron": "15 3 * * *",
        "configuration": {
            "coverage": "national",
            "dataset_type": "climate",
            "metric": "precipitation",
            "daily_aggregation": "sum",
            "bootstrap_from": "2018-01-01",
            "max_backfill_days": 366,
            "verified_on": "2026-07-13",
            "publisher": "Oficina de Informática IDEAM",
        },
    },
    {
        "id": "ideam-temperature",
        "name": "Temperatura Ambiente del Aire",
        "institution": "IDEAM",
        "source_type": "socrata",
        "endpoint": "https://www.datos.gov.co/resource/sbwg-7ju4.json",
        "dataset_id": "sbwg-7ju4",
        "status": SourceStatus.ACTIVE.value,
        "refresh_cron": "20 3 * * *",
        "configuration": {
            "coverage": "national",
            "dataset_type": "climate",
            "metric": "temperature",
            "daily_aggregation": "avg",
            "bootstrap_from": "2018-01-01",
            "max_backfill_days": 366,
            "verified_on": "2026-07-13",
            "publisher": "Oficina de Informática IDEAM",
        },
    },
    {
        "id": "ideam-humidity",
        "name": "Humedad del Aire",
        "institution": "IDEAM",
        "source_type": "socrata",
        "endpoint": "https://www.datos.gov.co/resource/uext-mhny.json",
        "dataset_id": "uext-mhny",
        "status": SourceStatus.ACTIVE.value,
        "refresh_cron": "25 3 * * *",
        "configuration": {
            "coverage": "national",
            "dataset_type": "climate",
            "metric": "humidity",
            "daily_aggregation": "avg",
            "bootstrap_from": "2018-01-01",
            "max_backfill_days": 366,
            "verified_on": "2026-07-13",
            "publisher": "Oficina de Informática IDEAM",
        },
    },
    {
        "id": "ideam-stations",
        "name": "Catálogo nacional de estaciones",
        "institution": "IDEAM",
        "source_type": "socrata",
        "endpoint": "https://www.datos.gov.co/resource/hp9r-jxuu.json",
        "dataset_id": "hp9r-jxuu",
        "status": SourceStatus.ACTIVE.value,
        "refresh_cron": "0 2 1 * *",
        "configuration": {
            "coverage": "national",
            "dataset_type": "weather_stations",
            "verified_on": "2026-07-13",
            "publisher": "Oficina de Informática IDEAM",
        },
    },
    {
        "id": "sivigila-national",
        "name": "Datos agregados de Vigilancia en Salud Pública de Colombia",
        "institution": "INS",
        "source_type": "socrata",
        "endpoint": "https://www.datos.gov.co/resource/4hyg-wa9d.json",
        "dataset_id": "4hyg-wa9d",
        "status": SourceStatus.ACTIVE.value,
        "refresh_cron": "0 4 1 * *",
        "configuration": {
            "coverage": "national",
            "dataset_type": "epidemiology",
            "territorial_resolution": "municipality",
            "temporal_resolution": "epidemiological_week",
            "minimum_year": 2018,
            "data_through_year": 2022,
            "stale_for_current_monitoring": True,
            "ira_proxy_event": "IRAG 348",
            "mortality_events_excluded": [540, 580],
            "verified_on": "2026-07-13",
            "publisher": "Instituto Nacional de Salud - INS",
        },
    },
    {
        "id": "sivigila-microdata-2024",
        "name": "SIVIGILA microdatos publicos anonimizados 2024",
        "institution": "INS",
        "source_type": "official-xlsx-set",
        "endpoint": ("https://portalsivigila.ins.gov.co/Microdatos/Forms/AllItems.aspx"),
        "status": SourceStatus.ACTIVE.value,
        "refresh_cron": "0 6 15 9 *",
        "configuration": {
            "coverage": "national",
            "dataset_type": "epidemiology",
            "territorial_resolution": "municipality",
            "temporal_resolution": "epidemiological_week",
            "data_through_year": 2024,
            "stale_for_current_monitoring": True,
            "publication_kind": "annual anonymised event workbooks",
            "discovery": "SharePoint document library",
            "direct_file_template": (
                "https://portalsivigila.ins.gov.co/Microdatos/Datos_2024_{event_code}.xlsx"
            ),
            "event_codes": [
                210,
                217,
                220,
                345,
                348,
                420,
                430,
                440,
                460,
                470,
                490,
                495,
                895,
                995,
            ],
            # Scheduled refreshes keep only measures with compatible case
            # semantics; centinela/collective IRA files remain opt-in context.
            "scheduled_event_codes": [
                210,
                220,
                217,
                348,
                420,
                430,
                440,
                460,
                470,
                490,
                495,
                895,
            ],
            "canonical_ira_proxy_event": 348,
            "ira_context_only_events": [345, 995],
            "patient_level_columns_allowed_in_canonical_store": False,
            "raw_workbook_persistence": False,
            "snapshot_policy": "sanitised municipality/week aggregates only",
            "adapter_version": "sivigila-microdata-2024-v1.0",
            "verified_http_status": 200,
            "verified_files_last_modified": "2025-09-13",
            "verified_on": "2026-07-13",
            "publisher": "Instituto Nacional de Salud - INS",
        },
    },
    {
        "id": "sivigila-current-authorized",
        "name": "SIVIGILA reciente autorizado 2025+ (entrega institucional)",
        "institution": "INS",
        "source_type": "institutional-file",
        "endpoint": "https://portalsivigila.ins.gov.co/buscador",
        "status": SourceStatus.REQUIRES_CONFIGURATION.value,
        "refresh_cron": None,
        "configuration": {
            "dataset_type": "epidemiology",
            "territorial_resolution": "municipality",
            "temporal_resolution": "epidemiological_week",
            "reason": (
                "Complementa la federación territorial abierta. Para cobertura nacional "
                "operativa 2025+ aún se requiere entrega institucional agregada o "
                "publicación tabular nacional verificable."
            ),
            "patient_level_data_allowed": False,
            "publisher": "Instituto Nacional de Salud - INS",
        },
    },
    {
        "id": "sivigila-territorial-open",
        "name": "SIVIGILA territorial abierto (federación datos.gov.co)",
        "institution": "Entidades territoriales / datos.gov.co",
        "source_type": "socrata-federation",
        "endpoint": "https://www.datos.gov.co/",
        "status": SourceStatus.ACTIVE.value,
        "refresh_cron": "30 5 * * 1",
        "configuration": {
            "coverage": "multi_territory",
            "dataset_type": "epidemiology",
            "territorial_resolution": "municipality",
            "temporal_resolution": "epidemiological_week",
            "federation": True,
            "member_source_ids": [
                "sivigila-boyaca-events",
                "sivigila-caqueta-dengue",
                "sivigila-pereira-dengue",
                "sivigila-tulua-dengue",
                "sivigila-bucaramanga-dengue",
                "sivigila-bucaramanga-events",
                "sivigila-bucaramanga-ira",
                "sivigila-casanare-dengue",
                "sivigila-santa-rosa-cabal-events",
            ],
            "purpose": (
                "Extiende series municipio-semana con publicaciones territoriales "
                "abiertas (Bucaramanga multi-evento e IRA hasta 2025, Santa Rosa "
                "2022–2024, entre otras). No sustituye SIVIGILA nacional completo; "
                "se agrega sin persistir microdatos nominales."
            ),
            "merge_policy": "prefer_newer_epidemiological_year",
            "verified_on": "2026-07-14",
            "publisher": "Gobernaciones y alcaldías publicantes en datos.gov.co",
        },
    },
    {
        "id": "sivigila-boyaca-events",
        "name": "SIVIGILA eventos notificados — Boyacá",
        "institution": "Gobernación de Boyacá",
        "source_type": "socrata",
        "endpoint": "https://www.datos.gov.co/resource/tz38-fg9k.json",
        "dataset_id": "tz38-fg9k",
        "status": SourceStatus.ACTIVE.value,
        "refresh_cron": "0 6 * * 2",
        "configuration": {
            "coverage": "department",
            "dataset_type": "epidemiology",
            "territorial_resolution": "municipality",
            "temporal_resolution": "epidemiological_week",
            "adapter": "territorial_sivigila",
            "year_from": 2019,
            "year_to": 2023,
            "federation_parent": "sivigila-territorial-open",
            "verified_on": "2026-07-14",
        },
    },
    {
        "id": "sivigila-caqueta-dengue",
        "name": "Casos de Dengue — Departamento del Caquetá",
        "institution": "Gobernación del Caquetá",
        "source_type": "socrata",
        "endpoint": "https://www.datos.gov.co/resource/fhz2-4x64.json",
        "dataset_id": "fhz2-4x64",
        "status": SourceStatus.ACTIVE.value,
        "refresh_cron": "15 6 * * 2",
        "configuration": {
            "coverage": "department",
            "dataset_type": "epidemiology",
            "territorial_resolution": "municipality",
            "temporal_resolution": "epidemiological_week",
            "adapter": "territorial_sivigila",
            "year_from": 2018,
            "year_to": 2023,
            "related_dataset_ids": ["qwsm-wq4w"],
            "federation_parent": "sivigila-territorial-open",
            "verified_on": "2026-07-14",
        },
    },
    {
        "id": "sivigila-pereira-dengue",
        "name": "Casos de dengue — ciudad de Pereira",
        "institution": "Alcaldía de Pereira",
        "source_type": "socrata",
        "endpoint": "https://www.datos.gov.co/resource/tm62-e28n.json",
        "dataset_id": "tm62-e28n",
        "status": SourceStatus.ACTIVE.value,
        "refresh_cron": "30 6 * * 2",
        "configuration": {
            "coverage": "municipality",
            "dataset_type": "epidemiology",
            "adapter": "territorial_sivigila",
            "year_from": 2017,
            "year_to": 2024,
            "federation_parent": "sivigila-territorial-open",
            "verified_on": "2026-07-14",
        },
    },
    {
        "id": "sivigila-tulua-dengue",
        "name": "Casos de Dengue — Municipio de Tuluá",
        "institution": "Alcaldía de Tuluá",
        "source_type": "socrata",
        "endpoint": "https://www.datos.gov.co/resource/dq2k-gub9.json",
        "dataset_id": "dq2k-gub9",
        "status": SourceStatus.ACTIVE.value,
        "refresh_cron": "45 6 * * 2",
        "configuration": {
            "coverage": "municipality",
            "dataset_type": "epidemiology",
            "adapter": "territorial_sivigila",
            "year_from": 2022,
            "year_to": 2024,
            "federation_parent": "sivigila-territorial-open",
            "verified_on": "2026-07-14",
        },
    },
    {
        "id": "sivigila-bucaramanga-dengue",
        "name": "Dengue — Municipio de Bucaramanga (hasta 2025)",
        "institution": "Alcaldía de Bucaramanga",
        "source_type": "socrata",
        "endpoint": "https://www.datos.gov.co/resource/qzc7-jbg3.json",
        "dataset_id": "qzc7-jbg3",
        "status": SourceStatus.ACTIVE.value,
        "refresh_cron": "0 7 * * 2",
        "configuration": {
            "coverage": "municipality",
            "dataset_type": "epidemiology",
            "adapter": "territorial_sivigila",
            "year_from": 2015,
            "year_to": 2025,
            "federation_parent": "sivigila-territorial-open",
            "extends_beyond_national_microdata_2024": True,
            "verified_on": "2026-07-14",
        },
    },
    {
        "id": "sivigila-casanare-dengue",
        "name": "Casos de Dengue — Casanare",
        "institution": "Gobernación de Casanare",
        "source_type": "socrata",
        "endpoint": "https://www.datos.gov.co/resource/3kuf-t86h.json",
        "dataset_id": "3kuf-t86h",
        "status": SourceStatus.ACTIVE.value,
        "refresh_cron": "15 7 * * 2",
        "configuration": {
            "coverage": "department",
            "dataset_type": "epidemiology",
            "adapter": "territorial_sivigila",
            "year_from": 2018,
            "year_to": 2023,
            "federation_parent": "sivigila-territorial-open",
            "verified_on": "2026-07-14",
        },
    },
    {
        "id": "sivigila-bucaramanga-events",
        "name": "EISP multi-evento — Bucaramanga (hasta 2025)",
        "institution": "Alcaldía de Bucaramanga",
        "source_type": "socrata",
        "endpoint": "https://www.datos.gov.co/resource/map9-mdzc.json",
        "dataset_id": "map9-mdzc",
        "status": SourceStatus.ACTIVE.value,
        "refresh_cron": "20 7 * * 2",
        "configuration": {
            "coverage": "municipality",
            "dataset_type": "epidemiology",
            "adapter": "territorial_sivigila",
            "year_from": 2015,
            "year_to": 2025,
            "federation_parent": "sivigila-territorial-open",
            "extends_beyond_national_microdata_2024": True,
            "verified_on": "2026-07-14",
        },
    },
    {
        "id": "sivigila-bucaramanga-ira",
        "name": "IRA/IRAG colectiva — Bucaramanga (hasta 2025)",
        "institution": "Alcaldía de Bucaramanga",
        "source_type": "socrata",
        "endpoint": "https://www.datos.gov.co/resource/dtct-ww7w.json",
        "dataset_id": "dtct-ww7w",
        "status": SourceStatus.ACTIVE.value,
        "refresh_cron": "25 7 * * 2",
        "configuration": {
            "coverage": "municipality",
            "dataset_type": "epidemiology",
            "adapter": "territorial_sivigila",
            "year_from": 2015,
            "year_to": 2025,
            "fixed_municipality_code": "68001",
            "federation_parent": "sivigila-territorial-open",
            "extends_beyond_national_microdata_2024": True,
            "verified_on": "2026-07-14",
        },
    },
    {
        "id": "sivigila-santa-rosa-cabal-events",
        "name": "Casos epidemiológicos — Santa Rosa de Cabal",
        "institution": "Alcaldía de Santa Rosa de Cabal",
        "source_type": "socrata",
        "endpoint": "https://www.datos.gov.co/resource/xc7d-5tmm.json",
        "dataset_id": "xc7d-5tmm",
        "status": SourceStatus.ACTIVE.value,
        "refresh_cron": "30 7 * * 2",
        "configuration": {
            "coverage": "municipality",
            "dataset_type": "epidemiology",
            "adapter": "territorial_sivigila",
            "year_from": 2022,
            "year_to": 2024,
            "federation_parent": "sivigila-territorial-open",
            "verified_on": "2026-07-14",
        },
    },
    {
        "id": "ins-irca-water-quality",
        "name": "Calidad del agua para consumo humano (IRCA)",
        "institution": "INS",
        "source_type": "socrata",
        "endpoint": "https://www.datos.gov.co/resource/nxt2-39c3.json",
        "dataset_id": "nxt2-39c3",
        "status": SourceStatus.ACTIVE.value,
        "refresh_cron": "0 8 1 * *",
        "configuration": {
            "coverage": "national",
            "dataset_type": "socioeconomic",
            "adapter": "irca_municipal",
            "territorial_resolution": "municipality",
            "temporal_resolution": "annual",
            "year_from": 2013,
            "year_to": 2024,
            "purpose": (
                "Índice IRCA municipal anual como covariable estructural de agua; "
                "no se interpreta como cobertura de acueducto CNPV."
            ),
            "verified_on": "2026-07-14",
            "publisher": "Instituto Nacional de Salud",
        },
    },
    {
        "id": "pai-valle-municipal",
        "name": "Cobertura de vacunación PAI — Valle del Cauca",
        "institution": "Gobernación del Valle del Cauca",
        "source_type": "socrata",
        "endpoint": "https://www.datos.gov.co/resource/uw8e-gzpp.json",
        "dataset_id": "uw8e-gzpp",
        "status": SourceStatus.ACTIVE.value,
        "refresh_cron": "45 7 * * 3",
        "configuration": {
            "coverage": "department",
            "dataset_type": "vaccination",
            "adapter": "pai_territorial_socrata",
            "territorial_resolution": "municipality",
            "temporal_resolution": "month",
            "year_from": 2022,
            "year_to": 2022,
            "federation_note": "Complementa ZIP PAI nacional con serie territorial abierta",
            "verified_on": "2026-07-14",
        },
    },
    {
        "id": "ins-bes-weekly",
        "name": "Boletin Epidemiologico Semanal 2026",
        "institution": "INS",
        "source_type": "official-pdf",
        "endpoint": (
            "https://www.ins.gov.co/buscador-eventos/BoletinEpidemiologico/Forms/AllItems.aspx"
        ),
        "status": SourceStatus.ACTIVE.value,
        "refresh_cron": "0 12 * * 5",
        "configuration": {
            "coverage": "national",
            "dataset_type": "epidemiology_current_reference",
            "territorial_resolution": "department_or_certified_district",
            "temporal_resolution": "weekly_bulletin",
            "comparison_semantics": (
                "INS publishes cumulative and/or expected-observed values by event; "
                "this layer is not silently merged into municipal training rows."
            ),
            "url_templates": [
                (
                    "https://www.ins.gov.co/BibliotecaDigital/"
                    "{year}-boletin-epidemiologico-semana-{week}.pdf"
                ),
                (
                    "https://www.ins.gov.co/buscador-eventos/BoletinEpidemiologico/"
                    "{year}_Boletin_epidemiologico_semana_{week}.pdf"
                ),
            ],
            "lookback_weeks": 10,
            "adapter_version": "ins-bes-v1.0",
            "verified_latest_document": (
                "https://www.ins.gov.co/BibliotecaDigital/2026-boletin-epidemiologico-semana-26.pdf"
            ),
            "verified_period_end": "2026-07-04",
            "verified_on": "2026-07-13",
            "publisher": "Instituto Nacional de Salud - INS",
            "is_tabular_api": False,
        },
    },
    {
        "id": "pai-national",
        "name": "Coberturas administrativas PAI",
        "institution": "Ministerio de Salud y Protección Social",
        "source_type": "socrata",
        "endpoint": "https://www.datos.gov.co/resource/6i25-2hdt.json",
        "dataset_id": "6i25-2hdt",
        "status": SourceStatus.ACTIVE.value,
        "refresh_cron": "0 4 5 1 *",
        "configuration": {
            "coverage": "national",
            "dataset_type": "vaccination_department",
            "territorial_resolution": "department",
            "temporal_resolution": "year",
            "data_years": [2019, 2020, 2021, 2022],
            "verified_on": "2026-07-13",
            "publisher": "Ministerio de Salud y Protección Social",
        },
    },
    {
        "id": "pai-municipal-history",
        "name": "Coberturas de vacunación municipal 1998–2025",
        "institution": "Ministerio de Salud y Protección Social",
        "source_type": "public-file",
        "endpoint": (
            "https://www.minsalud.gov.co/sites/rid/Lists/BibliotecaDigital/RIDE/VS/PP/PAI/"
            "coberturas-vacunacion-municipal-desde-1998.zip"
        ),
        "status": SourceStatus.ACTIVE.value,
        "refresh_cron": "0 4 7 2 *",
        "configuration": {
            "coverage": "national",
            "dataset_type": "vaccination_municipality",
            "territorial_resolution": "municipality",
            "temporal_resolution": "year",
            "data_years": [1998, 2025],
            "archive_sha256": ("5e9d3c8677252f7b88867173ae13600c84901e03c97a6981e8ae74479e8ea2db"),
            "adapter_version": "pai-municipal-v1.1",
            "verified_on": "2026-07-13",
            "publisher": "Ministerio de Salud y Protección Social",
        },
    },
    {
        "id": "pai-municipal-2026",
        "name": "Dosis y coberturas municipales PAI 2026",
        "institution": "Ministerio de Salud y Protección Social",
        "source_type": "public-file",
        "endpoint": (
            "https://www.minsalud.gov.co/sites/rid/Lists/BibliotecaDigital/RIDE/VS/PP/PAI/"
            "dosis-coberturas-biologicos-municipios-2026.zip"
        ),
        "status": SourceStatus.ACTIVE.value,
        "refresh_cron": "0 4 7 * *",
        "configuration": {
            "coverage": "national",
            "dataset_type": "vaccination_municipality",
            "territorial_resolution": "municipality",
            "temporal_resolution": "month_cutoff",
            "available_cutoffs": ["2026-01", "2026-02"],
            "archive_sha256": ("582ab20337fb52c97798cabd724d6725e7dea56248e153d0bbea9ddfa5e6dc40"),
            "adapter_version": "pai-municipal-v1.1",
            "verified_on": "2026-07-13",
            "publisher": "Ministerio de Salud y Protección Social",
        },
    },
    {
        "id": "ideam-deforestation",
        "name": "Sistema de Monitoreo de Bosques y Carbono",
        "institution": "IDEAM",
        "source_type": "geospatial-file",
        "endpoint": (
            "https://visualizador.ideam.gov.co/portal/apps/experiencebuilder/experience/"
            "?id=d6e559d3816f4a059b20869d04203993"
        ),
        "status": SourceStatus.REQUIRES_CONFIGURATION.value,
        "refresh_cron": "0 5 10 1,4,7,10 *",
        "configuration": {
            "reason": (
                "La fuente oficial publica boletines y archivos geoespaciales sin "
                "API tabular estable."
            ),
            "accepted_formats": ["zip", "geojson", "gpkg", "shp"],
        },
    },
    {
        "id": "dane-socioeconomic",
        "name": "CNPV 2018 - servicios públicos y población municipal",
        "institution": "DANE",
        "source_type": "arcgis-rest",
        "endpoint": (
            "https://geoportal.dane.gov.co/mparcgis/rest/services/MARCO_INTEGRADO/"
            "Serv_DatosCNPV2018_Integrados_MGN2018/MapServer/800/query"
        ),
        "status": SourceStatus.ACTIVE.value,
        "refresh_cron": "0 5 1 1 *",
        "configuration": {
            "coverage": "national",
            "dataset_type": "socioeconomic",
            "territorial_resolution": "municipality",
            "vintage": 2018,
            "class_composition_endpoint": (
                "https://geoportal.dane.gov.co/mparcgis/rest/services/MARCO_INTEGRADO/"
                "Serv_DatosCNPV2018_Integrados_MGN2018/MapServer/801/query"
            ),
            "indicators": [
                "water_access_pct",
                "sewer_access_pct",
                "population",
                "urban_population_pct",
                "rural_population_pct",
                "populated_center_population_pct",
                "rural_remainder_population_pct",
            ],
            "urban_rural_policy": (
                "DANE CNPV 2018 layer 801: urban=CLAS_CCDGO 1 cabecera; "
                "rural=CLAS_CCDGO 2 centro poblado + 3 area resto municipal"
            ),
            "verified_on": "2026-07-13",
            "publisher": "DANE",
        },
    },
)


async def seed_source_catalog(session: AsyncSession) -> list[DataSource]:
    sources: list[DataSource] = []
    for item in OFFICIAL_SOURCE_CATALOG:
        source = await session.get(DataSource, item["id"])
        if source is None:
            source = DataSource(**item)
            session.add(source)
        else:
            previous_status = source.status
            for field, value in item.items():
                if field != "status":
                    setattr(source, field, value)
            desired_status = str(item["status"])
            if previous_status in {
                SourceStatus.REQUIRES_CONFIGURATION.value,
                SourceStatus.DISABLED.value,
            } or desired_status in {
                SourceStatus.REQUIRES_CONFIGURATION.value,
                SourceStatus.DISABLED.value,
            }:
                source.status = desired_status
        sources.append(source)
    await session.commit()
    return sources
