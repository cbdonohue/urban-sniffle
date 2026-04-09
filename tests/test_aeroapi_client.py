"""Unit tests for AeroAPI client helpers and paging."""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.aeroapi_client import (
    AeroAPIError,
    _collect_flights_search,
    _collect_positions_search,
    _cursor_from_next_link,
    _format_latlon_query,
    _format_positions_query,
    _safe_error_body,
    search_flights_near,
)
from app.geo import BoundingBox


def test_format_latlon_query():
    bbox = BoundingBox(
        min_lat=1.0, min_lon=2.0, max_lat=3.0, max_lon=4.0
    )
    q = _format_latlon_query(bbox)
    assert '-latlong "1.0 2.0 3.0 4.0"' in q


def test_format_positions_query():
    bbox = BoundingBox(
        min_lat=10.0, min_lon=20.0, max_lat=30.0, max_lon=40.0
    )
    q = _format_positions_query(bbox)
    assert "{range lat 10.0 30.0}" in q
    assert "{range lon 20.0 40.0}" in q
    assert "{= updateType A}" in q


@pytest.mark.parametrize(
    "next_url,expected",
    [
        (None, None),
        ("", None),
        ("https://api.example/flights/search?cursor=abc", "abc"),
        ("https://api.example/flights/search?foo=1&cursor=xyz", "xyz"),
    ],
)
def test_cursor_from_next_link(next_url, expected):
    assert _cursor_from_next_link(next_url) == expected


def test_safe_error_body_json():
    r = MagicMock(spec=httpx.Response)
    r.json.return_value = {"error": "bad"}
    assert _safe_error_body(r) == {"error": "bad"}


def test_safe_error_body_non_json():
    r = MagicMock(spec=httpx.Response)
    r.json.side_effect = ValueError("not json")
    r.text = "plain error"
    assert _safe_error_body(r) == "plain error"


def test_aeroapi_error_attributes():
    err = AeroAPIError(503, {"msg": "down"})
    assert err.status_code == 503
    assert err.body == {"msg": "down"}
    assert "503" in str(err)


@pytest.mark.anyio
async def test_collect_flights_search_single_page():
    client = AsyncMock(spec=httpx.AsyncClient)
    client.get = AsyncMock(
        return_value=httpx.Response(
            200,
            json={
                "num_pages": 1,
                "flights": [{"ident": "A"}],
                "links": {},
            },
        )
    )

    flights, meta = await _collect_flights_search(
        client,
        "https://aeroapi.example/aeroapi",
        "key",
        '-latlong "0 0 1 1"',
        max_pages=3,
    )

    assert flights == [{"ident": "A"}]
    assert meta["num_pages_total"] == 1
    assert client.get.await_count == 1


@pytest.mark.anyio
async def test_collect_flights_search_http_error_raises():
    client = AsyncMock(spec=httpx.AsyncClient)
    client.get = AsyncMock(
        return_value=httpx.Response(401, json={"detail": "nope"})
    )

    with pytest.raises(AeroAPIError) as exc_info:
        await _collect_flights_search(
            client,
            "https://aeroapi.example/aeroapi",
            "key",
            "query",
            max_pages=1,
        )
    assert exc_info.value.status_code == 401
    assert exc_info.value.body == {"detail": "nope"}


@pytest.mark.anyio
async def test_collect_flights_search_follows_cursor():
    client = AsyncMock(spec=httpx.AsyncClient)
    client.get = AsyncMock(
        side_effect=[
            httpx.Response(
                200,
                json={
                    "num_pages": 1,
                    "flights": [{"ident": "A"}],
                    "links": {
                        "next": "https://aeroapi.example/aeroapi/flights/search?cursor=c1"
                    },
                },
            ),
            httpx.Response(
                200,
                json={
                    "num_pages": 1,
                    "flights": [{"ident": "B"}],
                    "links": {},
                },
            ),
        ]
    )

    flights, meta = await _collect_flights_search(
        client,
        "https://aeroapi.example/aeroapi",
        "key",
        "q",
        max_pages=5,
    )

    assert [f["ident"] for f in flights] == ["A", "B"]
    assert meta["num_pages_total"] == 2
    assert client.get.await_count == 2
    second_call = client.get.await_args_list[1]
    assert second_call.kwargs["params"]["cursor"] == "c1"


@pytest.mark.anyio
async def test_collect_positions_search_skips_non_dict_links():
    client = AsyncMock(spec=httpx.AsyncClient)
    client.get = AsyncMock(
        return_value=httpx.Response(
            200,
            json={
                "num_pages": 1,
                "positions": [{"latitude": 1.0, "longitude": 2.0}],
                "links": "broken",
            },
        )
    )

    positions, meta = await _collect_positions_search(
        client,
        "https://aeroapi.example/aeroapi",
        "key",
        "q",
        max_pages=2,
        unique_flights=True,
    )

    assert len(positions) == 1
    assert meta["num_pages_total"] == 1


@pytest.mark.anyio
async def test_search_flights_near_uses_positions_when_adsb_only():
    bbox = BoundingBox(0.0, 0.0, 1.0, 1.0)
    mock_collect = AsyncMock(
        return_value=([{"latitude": 1.0}], {"num_pages_total": 1})
    )

    with patch(
        "app.aeroapi_client._collect_positions_search",
        mock_collect,
    ):
        flights, meta = await search_flights_near(
            base_url="https://aeroapi.example/aeroapi",
            api_key="k",
            bbox=bbox,
            max_pages=1,
            adsb_only=True,
        )

    assert flights == [{"latitude": 1.0}]
    assert meta["num_pages_total"] == 1
    mock_collect.assert_awaited_once()
    call_kw = mock_collect.await_args
    assert call_kw.kwargs["unique_flights"] is True


@pytest.mark.anyio
async def test_search_flights_near_uses_flights_search_when_not_adsb():
    bbox = BoundingBox(0.0, 0.0, 1.0, 1.0)
    mock_collect = AsyncMock(
        return_value=([{"ident": "X"}], {"num_pages_total": 1})
    )

    with patch(
        "app.aeroapi_client._collect_flights_search",
        mock_collect,
    ):
        flights, meta = await search_flights_near(
            base_url="https://aeroapi.example/aeroapi/",
            api_key="k",
            bbox=bbox,
            max_pages=2,
            adsb_only=False,
        )

    assert flights == [{"ident": "X"}]
    assert meta["num_pages_total"] == 1
