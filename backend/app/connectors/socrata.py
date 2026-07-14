"""Hardened asynchronous client for the Socrata Open Data API (SODA)."""

from __future__ import annotations

import asyncio
import os
import random
import re
from collections.abc import AsyncIterator, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any

import httpx

from .errors import ConnectorError, UnsafeQueryError

_DATASET_ID = re.compile(r"^[a-z0-9]{4}-[a-z0-9]{4}$")
_IDENTIFIER = re.compile(r"^(?:[a-z_][a-z0-9_]*|:[a-z_][a-z0-9_]*)$")
_RETRYABLE_STATUS = {408, 425, 429, 500, 502, 503, 504}


class Operator(StrEnum):
    EQ = "="
    NE = "!="
    GT = ">"
    GTE = ">="
    LT = "<"
    LTE = "<="
    IN = "IN"
    NOT_IN = "NOT IN"
    IS_NULL = "IS NULL"
    IS_NOT_NULL = "IS NOT NULL"


class Function(StrEnum):
    DATE_TRUNC_YMD = "date_trunc_ymd"


class Aggregate(StrEnum):
    AVG = "avg"
    SUM = "sum"
    COUNT = "count"


@dataclass(frozen=True, slots=True)
class Filter:
    field: str
    operator: Operator | str
    value: Any = None


@dataclass(frozen=True, slots=True)
class SelectExpression:
    alias: str
    field: str | None = None
    function: Function | None = None
    aggregate: Aggregate | None = None
    distinct: bool = False


@dataclass(frozen=True, slots=True)
class GroupExpression:
    field: str
    function: Function


@dataclass(frozen=True, slots=True)
class SafeQuery:
    """Structured SoQL subset; raw query fragments are intentionally unsupported."""

    select: tuple[str | SelectExpression, ...] = ()
    filters: tuple[Filter, ...] = ()
    order_by: tuple[tuple[str, str], ...] = ()
    group_by: tuple[str | GroupExpression, ...] = ()

    def parameters(self) -> dict[str, str]:
        params: dict[str, str] = {}
        if self.select:
            params["$select"] = ",".join(_render_select(item) for item in self.select)
        if self.filters:
            params["$where"] = " AND ".join(_render_filter(item) for item in self.filters)
        if self.group_by:
            params["$group"] = ",".join(_render_group(item) for item in self.group_by)
        if self.order_by:
            rendered: list[str] = []
            for name, direction in self.order_by:
                normalized = direction.upper()
                if normalized not in {"ASC", "DESC"}:
                    raise UnsafeQueryError(f"Unsupported sort direction: {direction!r}")
                rendered.append(f"{_safe_identifier(name)} {normalized}")
            params["$order"] = ",".join(rendered)
        return params


def _safe_identifier(value: str) -> str:
    if not _IDENTIFIER.fullmatch(value):
        raise UnsafeQueryError(f"Unsafe SoQL identifier: {value!r}")
    return value


def _render_select(item: str | SelectExpression) -> str:
    if isinstance(item, str):
        return _safe_identifier(item)
    alias = _safe_identifier(item.alias)
    if item.function is not None and item.aggregate is not None:
        raise UnsafeQueryError("A select expression cannot combine function and aggregate")
    if item.function is not None:
        if item.field is None:
            raise UnsafeQueryError("A function select requires a field")
        expression = f"{item.function.value}({_safe_identifier(item.field)})"
    elif item.aggregate is not None:
        if item.aggregate is Aggregate.COUNT and item.field is None:
            expression = "count(*)"
        elif item.field is not None:
            field = _safe_identifier(item.field)
            argument = f"distinct {field}" if item.distinct else field
            expression = f"{item.aggregate.value}({argument})"
        else:
            raise UnsafeQueryError("This aggregate requires a field")
    else:
        raise UnsafeQueryError("SelectExpression requires a whitelisted operation")
    return f"{expression} AS {alias}"


def _render_group(item: str | GroupExpression) -> str:
    if isinstance(item, str):
        return _safe_identifier(item)
    return f"{item.function.value}({_safe_identifier(item.field)})"


def _literal(value: Any) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float, Decimal)) and not isinstance(value, bool):
        return str(value)
    if isinstance(value, (datetime, date)):
        value = value.isoformat()
    if not isinstance(value, str):
        raise UnsafeQueryError(f"Unsupported SoQL literal type: {type(value).__name__}")
    if any(ord(char) < 32 for char in value):
        raise UnsafeQueryError("Control characters are not permitted in SoQL literals")
    return "'" + value.replace("'", "''") + "'"


def _render_filter(item: Filter) -> str:
    field_name = _safe_identifier(item.field)
    try:
        operator = (
            item.operator
            if isinstance(item.operator, Operator)
            else Operator(item.operator.upper())
        )
    except ValueError as exc:
        raise UnsafeQueryError(f"Unsupported SoQL operator: {item.operator!r}") from exc
    if operator in {Operator.IS_NULL, Operator.IS_NOT_NULL}:
        return f"{field_name} {operator.value}"
    if operator in {Operator.IN, Operator.NOT_IN}:
        if (
            isinstance(item.value, (str, bytes))
            or not isinstance(item.value, Sequence)
            or not item.value
        ):
            raise UnsafeQueryError(f"{operator.value} requires a non-empty sequence")
        values = ",".join(_literal(value) for value in item.value)
        return f"{field_name} {operator.value} ({values})"
    return f"{field_name} {operator.value} {_literal(item.value)}"


@dataclass(slots=True)
class SocrataClient:
    """SODA v2 resource client with bounded pagination and resilient retries."""

    base_url: str = "https://www.datos.gov.co/resource"
    metadata_url: str = "https://www.datos.gov.co/api/views"
    app_token: str | None = None
    timeout_seconds: float = 30.0
    max_retries: int = 4
    backoff_base_seconds: float = 0.5
    max_page_size: int = 50_000
    client: httpx.AsyncClient | None = None
    sleep: Callable[[float], Any] = asyncio.sleep
    _owns_client: bool = field(default=False, init=False)

    @classmethod
    def from_env(cls, **overrides: Any) -> SocrataClient:
        """Build a client without leaking the optional token into callers or logs."""
        return cls(app_token=os.getenv("PRORA_SOCRATA_APP_TOKEN") or None, **overrides)

    async def __aenter__(self) -> SocrataClient:
        if self.client is None:
            self.client = httpx.AsyncClient(timeout=self.timeout_seconds, follow_redirects=True)
            self._owns_client = True
        return self

    async def __aexit__(self, *_: object) -> None:
        if self._owns_client and self.client is not None:
            await self.client.aclose()
            self.client = None
            self._owns_client = False

    async def fetch_page(
        self,
        dataset_id: str,
        *,
        query: SafeQuery | None = None,
        limit: int = 5_000,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        _validate_dataset_id(dataset_id)
        if limit < 1 or limit > self.max_page_size:
            raise ValueError(f"limit must be between 1 and {self.max_page_size}")
        if offset < 0:
            raise ValueError("offset cannot be negative")
        params = (query or SafeQuery()).parameters()
        params.update({"$limit": str(limit), "$offset": str(offset)})
        url = f"{self.base_url.rstrip('/')}/{dataset_id}.json"
        response = await self._request(url, params=params)
        payload = response.json()
        if not isinstance(payload, list) or any(not isinstance(row, dict) for row in payload):
            raise ConnectorError(f"Unexpected Socrata response shape for {dataset_id}")
        return payload

    async def fetch_metadata(self, dataset_id: str) -> dict[str, Any]:
        """Return the official Socrata view metadata used to pin snapshot identity."""
        _validate_dataset_id(dataset_id)
        url = f"{self.metadata_url.rstrip('/')}/{dataset_id}"
        response = await self._request(url, params={})
        payload = response.json()
        if not isinstance(payload, dict) or payload.get("id") != dataset_id:
            raise ConnectorError(f"Unexpected Socrata metadata for {dataset_id}")
        return payload

    async def paginate(
        self,
        dataset_id: str,
        *,
        query: SafeQuery | None = None,
        page_size: int = 5_000,
        max_records: int | None = None,
    ) -> AsyncIterator[list[dict[str, Any]]]:
        if max_records is not None and max_records < 1:
            raise ValueError("max_records must be positive")
        offset = 0
        while True:
            requested = (
                min(page_size, max_records - offset) if max_records is not None else page_size
            )
            if requested <= 0:
                return
            page = await self.fetch_page(dataset_id, query=query, limit=requested, offset=offset)
            if not page:
                return
            yield page
            offset += len(page)
            if len(page) < requested or (max_records is not None and offset >= max_records):
                return

    async def _request(self, url: str, *, params: Mapping[str, str]) -> httpx.Response:
        if self.client is None:
            self.client = httpx.AsyncClient(timeout=self.timeout_seconds, follow_redirects=True)
            self._owns_client = True
        headers = {
            "Accept": "application/json",
            "User-Agent": "PRORA/1.0 (+public-health-research)",
        }
        if self.app_token:
            headers["X-App-Token"] = self.app_token
        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                response = await self.client.get(url, params=params, headers=headers)
                if response.status_code not in _RETRYABLE_STATUS:
                    response.raise_for_status()
                    return response
                last_error = httpx.HTTPStatusError(
                    f"Retryable Socrata status {response.status_code}",
                    request=response.request,
                    response=response,
                )
                retry_after = _retry_after_seconds(response)
            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                last_error = exc
                retry_after = None
            if attempt >= self.max_retries:
                break
            delay = (
                retry_after if retry_after is not None else self.backoff_base_seconds * (2**attempt)
            )
            delay += random.uniform(0, min(delay * 0.1, 0.25))
            await self.sleep(delay)
        attempts = self.max_retries + 1
        raise ConnectorError(
            f"Socrata request failed after {attempts} attempts: {url}"
        ) from last_error


def _retry_after_seconds(response: httpx.Response) -> float | None:
    raw = response.headers.get("Retry-After")
    if raw is None:
        return None
    try:
        return max(float(raw), 0.0)
    except ValueError:
        return None


def _validate_dataset_id(dataset_id: str) -> None:
    if not _DATASET_ID.fullmatch(dataset_id):
        raise UnsafeQueryError(f"Invalid Socrata dataset identifier: {dataset_id!r}")
