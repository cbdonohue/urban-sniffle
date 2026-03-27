# Nearby flights API (FlightAware AeroAPI)

Small FastAPI service that searches for flights near a latitude and longitude using [FlightAware AeroAPI](https://www.flightaware.com/aeroapi/portal/documentation#overview). You need an API key from the [AeroAPI portal](https://www.flightaware.com/aeroapi/portal/).

## Setup

1. Create a virtual environment and install dependencies:

```bash
cd /path/to/this/repo
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

2. Set your API key (do not commit real keys):

```bash
export AEROAPI_API_KEY="your_key_here"
```

Optional: copy `.env.example` to `.env` and set `AEROAPI_API_KEY` there.

3. Run the server:

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

## Usage

- `GET /health` — liveness check.
- `GET /api/flights/near?lat=37.62&lon=-122.38&radius_miles=1` — flights with last position inside a bounding box around the point; by default results are filtered to a true circle using Haversine distance.

Query parameters:

| Parameter | Default | Description |
|-----------|---------|-------------|
| `lat`, `lon` | required | Center (WGS84) |
| `radius_miles` | `1` | Radius in statute miles (max 50) |
| `adsb_only` | `false` | Use `/flights/search/positions` with ADS-B-only filter |
| `max_pages` | `3` | Max AeroAPI pages to follow (capped at 20) |
| `strict_radius` | `true` | Keep only aircraft within the circular radius |

Example:

```bash
curl -s "http://127.0.0.1:8000/api/flights/near?lat=33.9425&lon=-118.4081&radius_miles=1"
```

Interactive docs: `http://127.0.0.1:8000/docs`

## Environment variables

| Variable | Required | Description |
|----------|----------|-------------|
| `AEROAPI_API_KEY` | yes | FlightAware AeroAPI key (`x-apikey` header) |
| `AEROAPI_BASE_URL` | no | Default `https://aeroapi.flightaware.com/aeroapi` |
