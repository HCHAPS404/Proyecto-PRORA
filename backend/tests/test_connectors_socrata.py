from __future__ import annotations

import asyncio

import httpx
import pytest

from app.connectors.errors import UnsafeQueryError
from app.connectors.socrata import Filter, Operator, SafeQuery, SocrataClient


def test_socrata_paginates_and_sends_app_token() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        offset = int(request.url.params["$offset"])
        rows = [{"id": offset + index} for index in range(2)] if offset == 0 else [{"id": offset}]
        return httpx.Response(200, json=rows, request=request)

    async def run() -> list[list[dict[str, int]]]:
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as http_client:
            client = SocrataClient(client=http_client, app_token="token-prora", max_page_size=10)
            return [page async for page in client.paginate("abcd-1234", page_size=2)]

    pages = asyncio.run(run())
    assert pages == [[{"id": 0}, {"id": 1}], [{"id": 2}]]
    assert [request.url.params["$offset"] for request in requests] == ["0", "2"]
    assert all(request.headers["X-App-Token"] == "token-prora" for request in requests)


def test_socrata_retries_rate_limit() -> None:
    attempts = 0
    delays: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(429, headers={"Retry-After": "0"}, request=request)
        return httpx.Response(200, json=[{"ok": True}], request=request)

    async def fake_sleep(delay: float) -> None:
        delays.append(delay)

    async def run() -> list[dict[str, bool]]:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
            client = SocrataClient(client=http_client, sleep=fake_sleep, max_retries=1)
            return await client.fetch_page("abcd-1234", limit=1)

    assert asyncio.run(run()) == [{"ok": True}]
    assert attempts == 2
    assert len(delays) == 1


def test_safe_query_rejects_identifiers_and_quotes_literals() -> None:
    with pytest.raises(UnsafeQueryError):
        SafeQuery(select=("ano; DROP TABLE",)).parameters()

    params = SafeQuery(filters=(Filter("municipio", Operator.EQ, "O'Brien"),)).parameters()
    assert params["$where"] == "municipio = 'O''Brien'"


def test_dataset_identifier_is_validated() -> None:
    async def run() -> None:
        client = SocrataClient()
        await client.fetch_page("../../secret", limit=1)

    with pytest.raises(UnsafeQueryError):
        asyncio.run(run())
