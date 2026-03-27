"""FastAPI application: nearby flights via AeroAPI."""

from __future__ import annotations

from functools import lru_cache
from typing import Annotated, Any

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field

from app.aeroapi_client import AeroAPIError, search_flights_near
from app.config import Settings, get_settings
from app.geo import bounding_box_from_center, haversine_miles
from app.map_image import render_nearby_flights_png

MAX_PAGES_CAP = 10


@lru_cache
def _cached_settings() -> Settings:
    return get_settings()


def settings_dep() -> Settings:
    return _cached_settings()


class LastPosition(BaseModel):
    """Aircraft position; extra AeroAPI fields are preserved on parse/serialize."""

    model_config = ConfigDict(extra="allow")

    latitude: float = Field(..., description="WGS84 latitude (degrees)")
    longitude: float = Field(..., description="WGS84 longitude (degrees)")
    heading: float | None = Field(
        None, description="True heading in degrees (0–360), if known"
    )


class NearbyFlightItem(BaseModel):
    """Stable JSON shape for clients (future frontend)."""

    ident: str | None = None
    fa_flight_id: str | None = None
    distance_miles: float | None = None
    last_position: LastPosition | None = None
    source: str = Field(
        description="aeroapi endpoint used: flights_search or positions_search"
    )


class NearbyFlightsResponse(BaseModel):
    center_lat: float = Field(..., description="Map center latitude (use this, not `lat`)")
    center_lon: float = Field(
        ..., description="Map center longitude (use this, not `lng` / `lon` query on POST)"
    )
    radius_miles: float
    adsb_only: bool
    strict_circle: bool
    max_pages: int
    num_pages_fetched: int | None = None
    flights: list[NearbyFlightItem]


app = FastAPI(
    title="Nearby flights (AeroAPI)",
    version="0.1.0",
    description="FlightAware AeroAPI proxy: flights near a lat/lon within a radius.",
)


def _flight_item_from_search_row(
    row: dict[str, Any],
    center_lat: float,
    center_lon: float,
    strict_circle: bool,
    radius_miles: float,
) -> NearbyFlightItem | None:
    lp = row.get("last_position")
    if not isinstance(lp, dict):
        return None
    lat = lp.get("latitude")
    lon = lp.get("longitude")
    if lat is None or lon is None:
        return None
    try:
        plat, plon = float(lat), float(lon)
    except (TypeError, ValueError):
        return None

    dist = haversine_miles(center_lat, center_lon, plat, plon)
    if strict_circle and dist > radius_miles:
        return None

    return NearbyFlightItem(
        ident=row.get("ident"),
        fa_flight_id=row.get("fa_flight_id"),
        distance_miles=round(dist, 4),
        last_position=lp,
        source="flights_search",
    )


def _flight_item_from_position_row(
    row: dict[str, Any],
    center_lat: float,
    center_lon: float,
    strict_circle: bool,
    radius_miles: float,
) -> NearbyFlightItem | None:
    lat = row.get("latitude")
    lon = row.get("longitude")
    if lat is None or lon is None:
        return None
    try:
        plat, plon = float(lat), float(lon)
    except (TypeError, ValueError):
        return None

    dist = haversine_miles(center_lat, center_lon, plat, plon)
    if strict_circle and dist > radius_miles:
        return None

    return NearbyFlightItem(
        ident=row.get("ident"),
        fa_flight_id=row.get("fa_flight_id"),
        distance_miles=round(dist, 4),
        last_position=row,
        source="positions_search",
    )


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/flights/near", response_model=NearbyFlightsResponse)
async def flights_near(
    settings: Annotated[Settings, Depends(settings_dep)],
    lat: float = Query(..., ge=-90, le=90, description="Center latitude (WGS84)"),
    lon: float = Query(..., ge=-180, le=180, description="Center longitude (WGS84)"),
    radius_miles: float = Query(
        1.0,
        gt=0,
        le=50,
        description="Search radius in statute miles (bounding box + optional circle)",
    ),
    adsb_only: bool = Query(
        False,
        description="If true, use /flights/search/positions with ADS-B update type only",
    ),
    strict_circle: bool = Query(
        True,
        description="If true, drop results whose position is outside the circle (not just the box)",
    ),
    max_pages: int = Query(
        1,
        ge=1,
        description="Max AeroAPI pages to fetch (capped)",
    ),
) -> NearbyFlightsResponse:
    capped = min(max_pages, MAX_PAGES_CAP)
    try:
        bbox = bounding_box_from_center(lat, lon, radius_miles)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e

    try:
        rows, meta = await search_flights_near(
            base_url=str(settings.aeroapi_base_url).rstrip("/"),
            api_key=settings.aeroapi_api_key,
            bbox=bbox,
            max_pages=capped,
            adsb_only=adsb_only,
        )
    except AeroAPIError as e:
        raise HTTPException(status_code=e.status_code, detail=e.body) from e

    items: list[NearbyFlightItem] = []
    if adsb_only:
        for row in rows:
            if not isinstance(row, dict):
                continue
            item = _flight_item_from_position_row(
                row, lat, lon, strict_circle, radius_miles
            )
            if item:
                items.append(item)
    else:
        for row in rows:
            if not isinstance(row, dict):
                continue
            item = _flight_item_from_search_row(
                row, lat, lon, strict_circle, radius_miles
            )
            if item:
                items.append(item)

    # Sort by distance when available
    items.sort(key=lambda x: (x.distance_miles is None, x.distance_miles or 0.0))

    return NearbyFlightsResponse(
        center_lat=lat,
        center_lon=lon,
        radius_miles=radius_miles,
        adsb_only=adsb_only,
        strict_circle=strict_circle,
        max_pages=capped,
        num_pages_fetched=meta.get("num_pages_total"),
        flights=items,
    )


@app.post(
    "/api/flights/near/image",
    responses={200: {"content": {"image/png": {}}}},
    summary="Render nearby flights as a PNG map",
)
async def flights_near_image(
    payload: NearbyFlightsResponse,
    width: int = Query(
        900,
        ge=200,
        le=2048,
        description="Output image width/height in pixels (square)",
    ),
) -> Response:
    """Draw the search circle, center crosshair, and aircraft positions from JSON."""
    try:
        png = render_nearby_flights_png(payload.model_dump(), size=width)
    except (KeyError, TypeError, ValueError) as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    return Response(content=png, media_type="image/png")
