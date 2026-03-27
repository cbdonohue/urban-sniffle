# Nearby flights backend (FlightAware AeroAPI)

Small [FastAPI](https://fastapi.tiangolo.com/) service that queries [FlightAware AeroAPI](https://www.flightaware.com/aeroapi/portal/documentation#overview) for flights near a latitude/longitude within a radius (default 1 statute mile). It uses a bounding box for the upstream query and optionally applies a circular (Haversine) filter so results match a true radius, not just the box corners.

**Requirements:** Python 3.11+, and an AeroAPI key from the [AeroAPI developer portal](https://www.flightaware.com/aeroapi/portal/documentation#overview).

## Configuration

1. Copy `.env.example` to `.env`.
2. Set `AEROAPI_API_KEY` to your key (header `x-apikey` is used automatically).

Optional: `AEROAPI_BASE_URL` (default `https://aeroapi.flightaware.com/aeroapi`).

## Run

```bash
pip install -r requirements.txt
export AEROAPI_API_KEY=your_key_here
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Install **all** lines from [`requirements.txt`](requirements.txt) before running the app or tests; the `pydantic-settings` package provides the `pydantic_settings` module. If you see `ModuleNotFoundError: No module named 'pydantic_settings'`, your environment is missing those dependencies.

Open interactive docs at `http://localhost:8000/docs`.

## API

- `GET /health` — liveness.
- `GET /api/flights/near` — query parameters:
  - `lat`, `lon` (required): center point (WGS84).
  - `radius_miles` (default `1`): search radius in statute miles.
  - `adsb_only` (default `false`): if `true`, uses `GET /flights/search/positions` with ADS-B positions only (`updateType A`). If `false`, uses `GET /flights/search` with `-latlong` (all supported position sources in the response).
  - `strict_circle` (default `true`): if `true`, drops points outside the circle even if they were inside the bounding box.
  - `max_pages` (default `1`, max `10`): how many AeroAPI pages to fetch (pagination cursor is followed automatically).

## Example

```bash
curl -s "http://localhost:8000/api/flights/near?lat=37.6213&lon=-122.3790&radius_miles=1"
```

## Tests

From the project root, with the same virtualenv you use for the app:

```bash
pip install -r requirements.txt -r requirements-dev.txt
PYTHONPATH=. pytest tests/ -v
```

`pytest-asyncio` is required so the `[tool.pytest.ini_options]` asyncio settings in `pyproject.toml` apply and async tests run correctly.

Data use is subject to FlightAware terms and your AeroAPI plan (rate limits and endpoint availability vary by subscription).
