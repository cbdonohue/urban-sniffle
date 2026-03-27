"""FastAPI application: nearby flights via AeroAPI."""

from __future__ import annotations

from functools import lru_cache
from typing import Annotated, Any

from fastapi import Depends, FastAPI, HTTPException, Query
from pydantic import BaseModel, Field

from app.aeroapi_client import AeroAPIError, search_airports_near, search_flights_near
from app.config import Settings, get_settings
from app.geo import bounding_box_from_center, haversine_miles

MAX_PAGES_CAP = 10


@lru_cache
def _cached_settings() -> Settings:
    return get_settings()


def settings_dep() -> Settings:
    return _cached_settings()


class NearbyFlightItem(BaseModel):
    """Stable JSON shape for clients (future frontend)."""

    ident: str | None = None
    fa_flight_id: str | None = None
    distance_miles: float | None = None
    last_position: dict[str, Any] | None = None
    source: str = Field(
        description="aeroapi endpoint used: flights_search or positions_search"
    )


class NearbyFlightsResponse(BaseModel):
    center_lat: float
    center_lon: float
    radius_miles: float
    adsb_only: bool
    strict_circle: bool
    max_pages: int
    num_pages_fetched: int | None = None
    flights: list[NearbyFlightItem]


class NearbyAirportItem(BaseModel):
    """Airport row from AeroAPI GET /airports/nearby (shape may vary by plan)."""

    model_config = {"extra": "allow"}

    airport_code: str | None = None
    code_icao: str | None = None
    code_iata: str | None = None
    code_lid: str | None = None
    name: str | None = None
    city: str | None = None
    state: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    timezone: str | None = None
    country_code: str | None = None
    distance: int | None = Field(
        default=None,
        description="Distance from search point (statute miles), per AeroAPI",
    )
    heading: int | None = None
    direction: str | None = None


class NearbyAirportsResponse(BaseModel):
    center_lat: float
    center_lon: float
    radius_miles: float
    only_iap: bool
    max_pages: int
    radius_sent_to_aeroapi: int = Field(
        description="Integer statute-mile radius passed to AeroAPI (rounded from radius_miles)"
    )
    num_pages_fetched: int | None = None
    airports: list[NearbyAirportItem]


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


@app.get("/api/airports/near", response_model=NearbyAirportsResponse)
async def airports_near(
    settings: Annotated[Settings, Depends(settings_dep)],
    lat: float = Query(..., ge=-90, le=90, description="Center latitude (WGS84)"),
    lon: float = Query(..., ge=-180, le=180, description="Center longitude (WGS84)"),
    radius_miles: float = Query(
        25.0,
        gt=0,
        le=500,
        description="Search radius in statute miles (sent to AeroAPI as a rounded integer)",
    ),
    only_iap: bool = Query(
        False,
        description="If true, only airports with instrument approaches (NA only per AeroAPI)",
    ),
    max_pages: int = Query(
        1,
        ge=1,
        description="Max AeroAPI pages to fetch (capped)",
    ),
) -> NearbyAirportsResponse:
    capped = min(max_pages, MAX_PAGES_CAP)
    radius_sent = max(1, int(round(radius_miles)))
    try:
        rows, meta = await search_airports_near(
            base_url=str(settings.aeroapi_base_url).rstrip("/"),
            api_key=settings.aeroapi_api_key,
            latitude=lat,
            longitude=lon,
            radius_miles=radius_miles,
            only_iap=only_iap,
            max_pages=capped,
        )
    except AeroAPIError as e:
        raise HTTPException(status_code=e.status_code, detail=e.body) from e

    items: list[NearbyAirportItem] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        items.append(NearbyAirportItem.model_validate(row))

    items.sort(
        key=lambda x: (
            x.distance is None,
            x.distance if x.distance is not None else 0,
        )
    )

    return NearbyAirportsResponse(
        center_lat=lat,
        center_lon=lon,
        radius_miles=radius_miles,
        only_iap=only_iap,
        max_pages=capped,
        radius_sent_to_aeroapi=radius_sent,
        num_pages_fetched=meta.get("num_pages_total"),
        airports=items,
    )
