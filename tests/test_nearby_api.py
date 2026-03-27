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


@pytest.mark.anyio
async def test_airports_near_returns_mocked(override_settings):
    sample_airport = {
        "airport_code": "KSFO",
        "code_icao": "KSFO",
        "code_iata": "SFO",
        "name": "San Francisco International",
        "city": "San Francisco",
        "state": "CA",
        "latitude": 37.6213,
        "longitude": -122.3790,
        "timezone": "America/Los_Angeles",
        "country_code": "US",
        "distance": 5,
        "heading": 270,
        "direction": "W",
    }

    async_mock = AsyncMock(
        return_value=([sample_airport], {"num_pages_total": 1})
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        with patch("app.main.search_airports_near", async_mock):
            r = await client.get(
                "/api/airports/near",
                params={"lat": 37.65, "lon": -122.4, "radius_miles": 25.0},
            )

    assert r.status_code == 200
    data = r.json()
    assert data["center_lat"] == 37.65
    assert data["radius_sent_to_aeroapi"] == 25
    assert len(data["airports"]) == 1
    assert data["airports"][0]["airport_code"] == "KSFO"
    assert data["airports"][0]["distance"] == 5
    async_mock.assert_awaited()
