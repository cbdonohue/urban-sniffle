"""Geographic helpers: bounding box from center + radius, Haversine distance."""

from __future__ import annotations

import math
from dataclasses import dataclass

# Mean Earth radius in statute miles (WGS84 approximation)
_EARTH_RADIUS_MI = 3958.7613


@dataclass(frozen=True)
class BoundingBox:
    min_lat: float
    min_lon: float
    max_lat: float
    max_lon: float


def bounding_box_from_center(lat: float, lon: float, radius_miles: float) -> BoundingBox:
    """Axis-aligned lat/lon box containing a circle of radius `radius_miles` at (lat, lon)."""
    if not (-90.0 <= lat <= 90.0):
        raise ValueError("latitude must be between -90 and 90")
    if not (-180.0 <= lon <= 180.0):
        raise ValueError("longitude must be between -180 and 180")
    if radius_miles <= 0:
        raise ValueError("radius_miles must be positive")

    lat_rad = math.radians(lat)
    dlat = radius_miles / 69.172
    cos_lat = max(math.cos(lat_rad), 1e-6)
    dlon = radius_miles / (69.172 * cos_lat)

    return BoundingBox(
        min_lat=max(-90.0, lat - dlat),
        max_lat=min(90.0, lat + dlat),
        min_lon=lon - dlon,
        max_lon=lon + dlon,
    )


def haversine_miles(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in statute miles between two WGS84 points."""
    p1 = math.radians(lat1), math.radians(lon1)
    p2 = math.radians(lat2), math.radians(lon2)
    dlat = p2[0] - p1[0]
    dlon = p2[1] - p1[1]
    a = math.sin(dlat / 2) ** 2 + math.cos(p1[0]) * math.cos(p2[0]) * math.sin(dlon / 2) ** 2
    c = 2 * math.asin(min(1.0, math.sqrt(a)))
    return _EARTH_RADIUS_MI * c
