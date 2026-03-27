"""FastAPI application: nearby flights via FlightAware AeroAPI."""

from __future__ import annotations

import logging
from functools import lru_cache
from typing import Any

from fastapi import FastAPI, HTTPException, Query

from app.aeroapi_client import (
    AeroAPIError,
    search_flights_in_box,
    search_positions_adsb_in_box,
)
from app.config import Settings
from app.geo import bounding_box_from_center, haversine_miles

logger = logging.getLogger(__name__)

MAX_PAGES_HARD_CAP = 20


@lru_cache
def get_settings() -> Settings:
    return Settings()


app = FastAPI(
    title="Nearby flights (AeroAPI)",
    version="0.1.0",
    description="Proxy for FlightAware AeroAPI flight search around a point.",
)


def _last_position_from_flight(flight: dict[str, Any]) -> dict[str, Any] | None:
    lp = flight.get("last_position")
    return lp if isinstance(lp, dict) else None


def _coords_from_flight_or_position(obj: dict[str, Any]) -> tuple[float, float] | None:
    lp = obj.get("last_position")
    if isinstance(lp, dict):
        la, lo = lp.get("latitude"), lp.get("longitude")
        if la is not None and lo is not None:
            return float(la), float(lo)
    la, lo = obj.get("latitude"), obj.get("longitude")
    if la is not None and lo is not None:
        return float(la), float(lo)
    return None


def _normalize_flight_item(
    raw: dict[str, Any],
    center_lat: float,
    center_lon: float,
    *,
    strict_radius: bool,
    radius_miles: float,
) -> dict[str, Any] | None:
    coords = _coords_from_flight_or_position(raw)
    if coords is None:
        return None
    plat, plon = coords
    dist = haversine_miles(center_lat, center_lon, plat, plon)
    if strict_radius and dist > radius_miles:
        return None

    out: dict[str, Any] = {
        "fa_flight_id": raw.get("fa_flight_id"),
        "ident": raw.get("ident"),
        "distance_miles": round(dist, 4),
    }
    lp = _last_position_from_flight(raw)
    if lp is not None:
        out["last_position"] = lp
    elif raw.get("latitude") is not None:
        out["last_position"] = {
            "latitude": raw.get("latitude"),
            "longitude": raw.get("longitude"),
            "altitude": raw.get("altitude"),
            "groundspeed": raw.get("groundspeed"),
            "heading": raw.get("heading"),
            "timestamp": raw.get("timestamp"),
            "update_type": raw.get("update_type"),
        }
    return out


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/flights/near")
async def flights_near(
    lat: float = Query(..., ge=-90.0, le=90.0, description="Center latitude (WGS84)"),
    lon: float = Query(..., ge=-180.0, le=180.0, description="Center longitude (WGS84)"),
    radius_miles: float = Query(
        1.0,
        gt=0.0,
        le=50.0,
        description="Search radius in statute miles",
    ),
    adsb_only: bool = Query(
        False,
        description="If true, use /flights/search/positions with ADS-B filter only",
    ),
    max_pages: int = Query(
        3,
        ge=1,
        le=MAX_PAGES_HARD_CAP,
        description="Max AeroAPI pages to fetch (upper bound)",
    ),
    strict_radius: bool = Query(
        True,
        description="If true, keep only results whose position is within the circle",
    ),
) -> dict[str, Any]:
    settings = get_settings()
    box = bounding_box_from_center(lat, lon, radius_miles)
    pages = min(max_pages, MAX_PAGES_HARD_CAP)

    try:
        if adsb_only:
            raw_list = await search_positions_adsb_in_box(
                settings, box, max_pages=pages
            )
        else:
            raw_list = await search_flights_in_box(settings, box, max_pages=pages)
    except AeroAPIError as e:
        logger.warning("AeroAPI error: %s", e.detail)
        raise HTTPException(status_code=e.status_code, detail=e.detail) from e

    seen: set[str] = set()
    results: list[dict[str, Any]] = []
    for raw in raw_list:
        if not isinstance(raw, dict):
            continue
        fid = raw.get("fa_flight_id")
        key = str(fid) if fid is not None else str(id(raw))
        if key in seen:
            continue
        item = _normalize_flight_item(
            raw, lat, lon, strict_radius=strict_radius, radius_miles=radius_miles
        )
        if item is None:
            continue
        seen.add(key)
        results.append(item)

    results.sort(key=lambda x: x.get("distance_miles") or 0.0)
    return {
        "center": {"latitude": lat, "longitude": lon},
        "radius_miles": radius_miles,
        "bounding_box": {
            "min_lat": box.min_lat,
            "min_lon": box.min_lon,
            "max_lat": box.max_lat,
            "max_lon": box.max_lon,
        },
        "adsb_only": adsb_only,
        "count": len(results),
        "flights": results,
    }
