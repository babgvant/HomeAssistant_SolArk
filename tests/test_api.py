"""Regression tests for the Sol-Ark API client."""
from __future__ import annotations

import asyncio

import aiohttp
import pytest

from custom_components.solark.api import (
    SolArkCloudAPI,
    SolArkCloudAPIError,
    SolArkCloudAuthenticationError,
)


class _Response:
    def __init__(self, status: int) -> None:
        self.status = status

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback) -> None:
        return None

    async def text(self) -> str:
        return "forbidden"

    async def json(self):
        return {"code": 0, "data": {}}

    def raise_for_status(self) -> None:
        if self.status >= 400:
            raise aiohttp.ClientResponseError(
                request_info=None,
                history=(),
                status=self.status,
            )


class _Session:
    def __init__(self, status: int) -> None:
        self.status = status

    def request(self, *args, **kwargs):
        return _Response(self.status)


def _api(status: int) -> SolArkCloudAPI:
    api = SolArkCloudAPI(
        username="user",
        password="password",
        plant_id="123",
        base_url="https://portal.example",
        api_url="https://api.example",
        session=_Session(status),
    )
    api._token = "valid-token"
    api._token_expiry = None

    async def _keep_token() -> None:
        return None

    api._ensure_token = _keep_token
    return api


def test_endpoint_forbidden_is_not_rejected_credentials() -> None:
    """A permission failure on one endpoint must not trigger reauthentication."""
    with pytest.raises(SolArkCloudAPIError) as raised:
        asyncio.run(_api(403)._request("GET", "/api/v1/batteries"))

    assert not isinstance(raised.value, SolArkCloudAuthenticationError)


def test_unauthorized_is_rejected_credentials() -> None:
    """A repeated unauthorized response remains an authentication failure."""
    with pytest.raises(SolArkCloudAuthenticationError):
        asyncio.run(
            _api(401)._request(
                "GET", "/api/v1/plant/123/realtime", retry_auth=False
            )
        )
