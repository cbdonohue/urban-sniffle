"""Unit tests for FastAPI handlers and flight row mapping."""

from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.aeroapi_client import AeroAPIError
from app.config import Settings
from app.main import (
    _flight_item_from_position_row,
    _flight_item_from_search_row,
    app,
    settings_dep,
)


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


def _sample_last_position(lat: float, lon: float) -> dict:
    return {
        "latitude": lat,
        "longitude": lon,
        "altitude": 100,
        "timestamp": "2026-01-01T12:00:00Z",
    }


def test_flight_item_from_search_row_valid():
    row = {"ident": "ABC", "fa_flight_id": "fa-1", "last_position": _sample_last_position(40.0, -74.0)}
    item = _flight_item_from_search_row(row, 40.0, -74.0, strict_circle=False, radius_miles=10.0)
    assert item is not None
    assert item.ident == "ABC"
    assert item.fa_flight_id == "fa-1"
    assert item.source == "flights_search"
    assert item.distance_miles is not None
    assert item.last_position == row["last_position"]


def test_flight_item_from_search_row_no_last_position():
    assert _flight_item_from_search_row({}, 0, 0, False, 1.0) is None


def test_flight_item_from_search_row_last_position_not_dict():
    assert _flight_item_from_search_row({"last_position": "x"}, 0, 0, False, 1.0) is None


def test_flight_item_from_search_row_missing_coordinates():
    lp = {"latitude": 40.0}
    assert _flight_item_from_search_row({"last_position": lp}, 40, -74, False, 1.0) is None


def test_flight_item_from_search_row_invalid_coordinate_types():
    lp = {"latitude": "nope", "longitude": -74.0}
    assert _flight_item_from_search_row({"last_position": lp}, 40, -74, False, 1.0) is None


def test_flight_item_from_search_row_strict_circle_excludes_outside():
    row = {"last_position": _sample_last_position(50.0, -74.0)}
    item = _flight_item_from_search_row(row, 40.0, -74.0, strict_circle=True, radius_miles=1.0)
    assert item is None


def test_flight_item_from_search_row_strict_circle_false_keeps_outside():
    row = {"last_position": _sample_last_position(50.0, -74.0)}
    item = _flight_item_from_search_row(row, 40.0, -74.0, strict_circle=False, radius_miles=1.0)
    assert item is not None
    assert item.distance_miles is not None


def test_flight_item_from_position_row_valid():
    row = {"ident": "P1", "latitude": 40.0, "longitude": -74.0, "heading": 90}
    item = _flight_item_from_position_row(row, 40.0, -74.0, False, 10.0)
    assert item is not None
    assert item.source == "positions_search"
    assert item.last_position == row


def test_flight_item_from_position_row_strict_circle_excludes():
    row = {"latitude": 50.0, "longitude": -74.0}
    assert _flight_item_from_position_row(row, 40.0, -74.0, True, 1.0) is None


@pytest.mark.anyio
async def test_health():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


@pytest.mark.anyio
async def test_flights_near_sorts_by_distance(override_settings):
    far = {
        "ident": "FAR",
        "last_position": _sample_last_position(40.05, -74.0),
    }
    near = {
        "ident": "NEAR",
        "last_position": _sample_last_position(40.001, -74.0),
    }
    async_mock = AsyncMock(return_value=([far, near], {"num_pages_total": 1}))

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        with patch("app.main.search_flights_near", async_mock):
            r = await client.get(
                "/api/flights/near",
                params={"lat": 40.0, "lon": -74.0, "radius_miles": 10.0},
            )

    assert r.status_code == 200
    ids = [f["ident"] for f in r.json()["flights"]]
    assert ids == ["NEAR", "FAR"]


@pytest.mark.anyio
async def test_flights_near_caps_max_pages(override_settings):
    async_mock = AsyncMock(return_value=([], {"num_pages_total": 0}))

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        with patch("app.main.search_flights_near", async_mock):
            r = await client.get(
                "/api/flights/near",
                params={
                    "lat": 0.0,
                    "lon": 0.0,
                    "max_pages": 99,
                },
            )

    assert r.status_code == 200
    assert r.json()["max_pages"] == 10
    call_kw = async_mock.await_args.kwargs
    assert call_kw["max_pages"] == 10


@pytest.mark.anyio
async def test_flights_near_aeroapi_error(override_settings):
    err = AeroAPIError(502, {"reason": "upstream"})
    async_mock = AsyncMock(side_effect=err)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        with patch("app.main.search_flights_near", async_mock):
            r = await client.get(
                "/api/flights/near",
                params={"lat": 0.0, "lon": 0.0},
            )

    assert r.status_code == 502
    assert r.json()["detail"] == {"reason": "upstream"}


@pytest.mark.anyio
async def test_flights_near_bbox_value_error_returns_422(override_settings):
    async_mock = AsyncMock(return_value=([], {}))

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        with (
            patch("app.main.search_flights_near", async_mock),
            patch(
                "app.main.bounding_box_from_center",
                side_effect=ValueError("bad box"),
            ),
        ):
            r = await client.get(
                "/api/flights/near",
                params={"lat": 0.0, "lon": 0.0},
            )

    assert r.status_code == 422
    assert r.json()["detail"] == "bad box"


@pytest.mark.anyio
async def test_flights_near_adsb_position_path(override_settings):
    pos_row = {"ident": "ADS", "latitude": 40.0, "longitude": -74.0}
    async_mock = AsyncMock(return_value=([pos_row], {"num_pages_total": 1}))

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        with patch("app.main.search_flights_near", async_mock):
            r = await client.get(
                "/api/flights/near",
                params={
                    "lat": 40.0,
                    "lon": -74.0,
                    "adsb_only": True,
                    "strict_circle": False,
                },
            )

    assert r.status_code == 200
    data = r.json()
    assert data["adsb_only"] is True
    assert len(data["flights"]) == 1
    assert data["flights"][0]["source"] == "positions_search"


@pytest.mark.anyio
async def test_flights_near_skips_non_dict_rows(override_settings):
    async_mock = AsyncMock(
        return_value=(
            ["not-a-dict", {"ident": "OK", "last_position": _sample_last_position(40.0, -74.0)}],
            {"num_pages_total": 1},
        )
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        with patch("app.main.search_flights_near", async_mock):
            r = await client.get(
                "/api/flights/near",
                params={"lat": 40.0, "lon": -74.0},
            )

    assert r.status_code == 200
    assert len(r.json()["flights"]) == 1
    assert r.json()["flights"][0]["ident"] == "OK"
