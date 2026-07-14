"""Non-destructive data-quality checks used before persistence and model training."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum


class Severity(StrEnum):
    WARNING = "warning"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class QualityIssue:
    code: str
    message: str
    field: str
    severity: Severity = Severity.WARNING


@dataclass(frozen=True, slots=True)
class QualityReport:
    issues: tuple[QualityIssue, ...] = ()

    @property
    def valid(self) -> bool:
        return all(issue.severity is not Severity.ERROR for issue in self.issues)

    @property
    def flags(self) -> tuple[str, ...]:
        return tuple(issue.code for issue in self.issues)


def report(*issues: QualityIssue | None) -> QualityReport:
    return QualityReport(tuple(issue for issue in issues if issue is not None))


def range_issue(field: str, value: float, minimum: float, maximum: float) -> QualityIssue | None:
    if minimum <= value <= maximum:
        return None
    return QualityIssue(
        "out_of_range",
        f"{field}={value} is outside [{minimum}, {maximum}]",
        field,
        Severity.ERROR,
    )


def nonnegative_issue(field: str, value: float) -> QualityIssue | None:
    if value >= 0:
        return None
    return QualityIssue("negative_value", f"{field} cannot be negative", field, Severity.ERROR)


def merge_reports(reports: Iterable[QualityReport]) -> QualityReport:
    return QualityReport(tuple(issue for item in reports for issue in item.issues))
