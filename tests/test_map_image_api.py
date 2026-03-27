import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


@pytest.mark.anyio
async def test_flights_near_image_returns_png():
    body = {
        "center_lat": 40.8501,
        "center_lon": -74.0608,
        "radius_miles": 1.0,
        "adsb_only": False,
        "strict_circle": True,
        "max_pages": 1,
        "num_pages_fetched": 1,
        "flights": [
            {
                "ident": "EJA744",
                "fa_flight_id": "EJA744-1774555231-sw-85p",
                "distance_miles": 0.5286,
                "last_position": {
                    "fa_flight_id": "EJA744-1774555231-sw-85p",
                    "altitude": -1,
                    "altitude_change": "D",
                    "groundspeed": 112,
                    "heading": 49,
                    "latitude": 40.84694,
                    "longitude": -74.07001,
                    "timestamp": "2026-03-27T16:12:12Z",
                    "update_type": "A",
                },
                "source": "flights_search",
            }
        ],
    }

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.post("/api/flights/near/image", json=body)

    assert r.status_code == 200
    assert r.headers["content-type"] == "image/png"
    assert r.content[:8] == b"\x89PNG\r\n\x1a\n"


@pytest.mark.anyio
async def test_flights_near_image_invalid_payload():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.post("/api/flights/near/image", json={})

    assert r.status_code == 422
