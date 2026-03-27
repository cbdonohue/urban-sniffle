from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.config import Settings
from app.main import app, settings_dep


@pytest.fixture
def test_settings():
    return Settings(
        aeroapi_api_key="test-key",
        aeroapi_base_url="https://aeroapi.flightaware.com/aeroapi",
    )


@pytest.fixture
def override_settings(test_settings):
    app.dependency_overrides[settings_dep] = lambda: test_settings
    yield
    app.dependency_overrides.clear()


@pytest.mark.anyio
async def test_flights_near_returns_sorted_mocked(override_settings):
    sample_flight = {
        "ident": "TEST123",
        "fa_flight_id": "fa-test-1",
        "last_position": {
            "latitude": 40.0001,
            "longitude": -74.0001,
            "altitude": 350,
            "altitude_change": "-",
            "groundspeed": 250,
            "heading": 90,
            "timestamp": "2026-01-01T12:00:00Z",
            "update_type": "A",
        },
    }

    async_mock = AsyncMock(
        return_value=([sample_flight], {"num_pages_total": 1})
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        with patch("app.main.search_flights_near", async_mock):
            r = await client.get(
                "/api/flights/near",
                params={"lat": 40.0, "lon": -74.0, "radius_miles": 1.0},
            )

    assert r.status_code == 200
    data = r.json()
    assert data["center_lat"] == 40.0
    assert len(data["flights"]) == 1
    assert data["flights"][0]["ident"] == "TEST123"
    assert data["flights"][0]["distance_miles"] is not None
    async_mock.assert_awaited()
