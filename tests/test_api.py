"""Regression tests for the Sol-Ark API client."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
import importlib.util
from pathlib import Path
import sys
import types
from unittest.mock import AsyncMock, patch

import aiohttp
import pytest

def load_api():
    """Exercise the real API client without importing the HA entry point."""
    root = Path(__file__).parents[1] / "custom_components" / "solark"
    package = types.ModuleType("solark_api_test")
    package.__path__ = [str(root)]
    with patch.dict(sys.modules, {"solark_api_test": package}):
        spec = importlib.util.spec_from_file_location("solark_api_test.api", root / "api.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    return module


API = load_api()
SolArkCloudAPI = API.SolArkCloudAPI
SolArkCloudAPIError = API.SolArkCloudAPIError
SolArkCloudAuthenticationError = API.SolArkCloudAuthenticationError


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


@pytest.mark.parametrize("zone,instant,expected", [
    ("America/Chicago", "2026-10-15T00:30:00+00:00", "2026-10-14"),
    ("America/Chicago", "2026-01-15T05:30:00+00:00", "2026-01-14"),
    ("Asia/Tokyo", "2026-10-15T23:30:00+00:00", "2026-10-16"),
])
def test_date_scoped_queries_use_configured_timezone(zone, instant, expected):
    api = SolArkCloudAPI("user", "password", "123", "https://portal.example",
                        "https://api.example", None, timezone=zone)
    fixed = datetime.fromisoformat(instant)

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return fixed.astimezone(tz)

    async def run():
        api._request = AsyncMock(return_value={"code": 0, "data": {}})
        api._ensure_token = AsyncMock()
        with patch.object(API, "datetime", Clock):
            await api.async_get_plant_flow()
            await api.async_get_inverter_measurements(1, "TEST", (16,))
            await api._get_flow_data()
        params = [call.args[2] for call in api._request.call_args_list]
        assert all(item["date"] == expected for item in params)
        assert params[1]["edate"] == expected

    asyncio.run(run())


@pytest.mark.parametrize("expired", [False, True])
def test_concurrent_token_renewal_logs_in_once(expired):
    async def run():
        api = SolArkCloudAPI("user", "password", "123", "https://portal.example",
                            "https://api.example", None)
        if expired:
            api._token = "old"
            api._token_expiry = datetime.utcnow() - timedelta(seconds=1)
        logins = 0

        async def login():
            nonlocal logins
            logins += 1
            await asyncio.sleep(0)
            api._token = "new"
            api._token_expiry = datetime.utcnow() + timedelta(hours=1)
            return True

        api.login = login
        await asyncio.gather(*(api._ensure_token() for _ in range(12)))
        assert logins == 1
        assert api._token == "new"

    asyncio.run(run())


def test_failed_login_releases_lock_for_retry():
    async def run():
        api = SolArkCloudAPI("user", "password", "123", "https://portal.example",
                            "https://api.example", None)
        api.login = AsyncMock(side_effect=SolArkCloudAuthenticationError("rejected"))
        with pytest.raises(SolArkCloudAuthenticationError):
            await api._ensure_token()
        api.login = AsyncMock()
        await asyncio.wait_for(api._ensure_token(), timeout=1)
        api.login.assert_awaited_once()

    asyncio.run(run())


def test_delayed_unauthorized_does_not_invalidate_replacement_token():
    async def run():
        api = SolArkCloudAPI("user", "password", "123", "https://portal.example",
                            "https://api.example", None)
        api._token = "old"
        api._token_expiry = datetime.utcnow() + timedelta(hours=1)
        api.login = AsyncMock(side_effect=AssertionError("replacement is still valid"))

        class DelayedResponse(_Response):
            async def text(self):
                api._token = "replacement"
                return "unauthorized"

        class Session:
            headers = []

            def request(self, *args, **kwargs):
                self.headers.append(kwargs["headers"]["Authorization"])
                return DelayedResponse(401) if len(self.headers) == 1 else _Response(200)

        session = Session()
        api._session = session
        await api._request("GET", "/api/v1/plant/123/realtime")
        assert session.headers == ["Bearer old", "Bearer replacement"]
        assert api._token == "replacement"

    asyncio.run(run())
