"""ORM model registry.

Importing this module registers every table in ``Base.metadata`` for Alembic
and the development-only automatic schema bootstrap.
"""

from app.models.entities import (
    AlertRule,
    Base,
    NotificationDelivery,
    RefreshSession,
    Subscription,
    User,
)
from app.models.epidemiology import (
    AlertEvent,
    ClimateObservation,
    DataSource,
    DeforestationObservation,
    DepartmentVaccinationCoverage,
    EpidemiologicalBulletinAggregate,
    EpidemiologicalObservation,
    Forecast,
    IngestionRun,
    ModelTrainingRun,
    ModelVersion,
    Municipality,
    QuarantineRecord,
    RawSnapshot,
    SocioeconomicIndicator,
    VaccinationCoverage,
    WeatherStation,
)

__all__ = [
    "AlertEvent",
    "AlertRule",
    "Base",
    "ClimateObservation",
    "DataSource",
    "DepartmentVaccinationCoverage",
    "DeforestationObservation",
    "EpidemiologicalObservation",
    "EpidemiologicalBulletinAggregate",
    "Forecast",
    "IngestionRun",
    "ModelTrainingRun",
    "ModelVersion",
    "Municipality",
    "NotificationDelivery",
    "QuarantineRecord",
    "RawSnapshot",
    "RefreshSession",
    "SocioeconomicIndicator",
    "Subscription",
    "User",
    "VaccinationCoverage",
    "WeatherStation",
]
