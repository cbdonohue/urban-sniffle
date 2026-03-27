"""Geodesy helpers: bounding box from center + radius, Haversine distance."""

from __future__ import annotations

import math
from dataclasses import dataclass

# Mean Earth radius (WGS84), statute miles
_EARTH_RADIUS_MI = 3958.7613


@dataclass(frozen=True)
class BoundingBox:
    min_lat: float
    min_lon: float
    max_lat: float
    max_lon: float


def bounding_box_from_center(lat: float, lon: float, radius_miles: float) -> BoundingBox:
    """
    Approximate axis-aligned lat/lon box containing a circle of radius `radius_miles`
    around (lat, lon). Suitable for small radii (e.g. a few miles).
    """
    if radius_miles <= 0:
        raise ValueError("radius_miles must be positive")
    if not (-90.0 <= lat <= 90.0):
        raise ValueError("lat must be between -90 and 90")
    if not (-180.0 <= lon <= 180.0):
        raise ValueError("lon must be between -180 and 180")

    lat_rad = math.radians(lat)
    dlat = radius_miles / _EARTH_RADIUS_MI
    dlon = radius_miles / (_EARTH_RADIUS_MI * max(math.cos(lat_rad), 1e-6))

    min_lat = lat - math.degrees(dlat)
    max_lat = lat + math.degrees(dlat)
    min_lon = lon - math.degrees(dlon)
    max_lon = lon + math.degrees(dlon)

    min_lat = max(min_lat, -90.0)
    max_lat = min(max_lat, 90.0)
    if min_lon < -180.0:
        min_lon += 360.0
    if max_lon > 180.0:
        max_lon -= 360.0

    return BoundingBox(
        min_lat=min_lat,
        min_lon=min_lon,
        max_lat=max_lat,
        max_lon=max_lon,
    )


def haversine_miles(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in statute miles between two WGS84 points."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlamb = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlamb / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(max(0.0, 1.0 - a)))
    return _EARTH_RADIUS_MI * c
