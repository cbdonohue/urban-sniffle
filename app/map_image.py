"""Render a PNG map of flights around a center point from nearby-flights JSON."""

from __future__ import annotations

import io
import math
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from app.geo import BoundingBox, bounding_box_from_center

# Image dimensions (square). Kept moderate for quick responses.
_DEFAULT_SIZE = 900
_MARGIN = 36
_MI_PER_DEG_LAT = 69.172
_CIRCLE_SAMPLES = 96


def _view_bounds(center_lat: float, center_lon: float, radius_miles: float) -> BoundingBox:
    """Slightly padded box around the search circle for framing."""
    pad = max(radius_miles * 0.12, 0.05)
    return bounding_box_from_center(center_lat, center_lon, radius_miles + pad)


def _lon_lat_to_xy(
    lon: float,
    lat: float,
    bbox: BoundingBox,
    width: int,
    height: int,
    margin: int,
) -> tuple[float, float]:
    lon_span = bbox.max_lon - bbox.min_lon
    lat_span = bbox.max_lat - bbox.min_lat
    if lon_span <= 0:
        lon_span = 1e-9
    if lat_span <= 0:
        lat_span = 1e-9
    inner_w = width - 2 * margin
    inner_h = height - 2 * margin
    x = margin + (lon - bbox.min_lon) / lon_span * inner_w
    y = margin + (bbox.max_lat - lat) / lat_span * inner_h
    return x, y


def _circle_outline_points(
    center_lat: float,
    center_lon: float,
    radius_miles: float,
    bbox: BoundingBox,
    width: int,
    height: int,
    margin: int,
) -> list[tuple[float, float]]:
    lat_rad = math.radians(center_lat)
    cos_lat = max(math.cos(lat_rad), 1e-6)
    pts: list[tuple[float, float]] = []
    for i in range(_CIRCLE_SAMPLES + 1):
        theta = 2 * math.pi * i / _CIRCLE_SAMPLES
        north_mi = radius_miles * math.cos(theta)
        east_mi = radius_miles * math.sin(theta)
        plat = center_lat + north_mi / _MI_PER_DEG_LAT
        plon = center_lon + east_mi / (_MI_PER_DEG_LAT * cos_lat)
        pts.append(_lon_lat_to_xy(plon, plat, bbox, width, height, margin))
    return pts


def _heading_line(
    x: float,
    y: float,
    heading_deg: float | None,
    length: float,
) -> tuple[tuple[float, float], tuple[float, float]] | None:
    if heading_deg is None:
        return None
    try:
        h = float(heading_deg)
    except (TypeError, ValueError):
        return None
    # Heading: degrees clockwise from north; screen y increases downward.
    hr = math.radians(h)
    dx = math.sin(hr) * length
    dy = -math.cos(hr) * length
    return (x, y), (x + dx, y + dy)


def render_nearby_flights_png(
    payload: dict[str, Any],
    size: int = _DEFAULT_SIZE,
) -> bytes:
    """Build a PNG showing the search circle, center, and flight markers."""
    center_lat = float(payload["center_lat"])
    center_lon = float(payload["center_lon"])
    radius_miles = float(payload["radius_miles"])
    flights = payload.get("flights") or []
    if not isinstance(flights, list):
        flights = []

    w = h = max(200, min(size, 2048))
    margin = min(_MARGIN, w // 12)
    bbox = _view_bounds(center_lat, center_lon, radius_miles)

    img = Image.new("RGB", (w, h), (15, 23, 42))
    draw = ImageDraw.Draw(img)

    # Subtle grid
    grid_color = (30, 41, 59)
    step = max(1, (w - 2 * margin) // 10)
    for gx in range(margin, w - margin + 1, step):
        draw.line([(gx, margin), (gx, h - margin)], fill=grid_color, width=1)
    for gy in range(margin, h - margin + 1, step):
        draw.line([(margin, gy), (w - margin, gy)], fill=grid_color, width=1)

    circle_pts = _circle_outline_points(
        center_lat, center_lon, radius_miles, bbox, w, h, margin
    )
    if len(circle_pts) >= 2:
        draw.line(circle_pts, fill=(100, 116, 139), width=2)

    cx, cy = _lon_lat_to_xy(center_lon, center_lat, bbox, w, h, margin)
    cross = 8
    draw.line([(cx - cross, cy), (cx + cross, cy)], fill=(248, 250, 252), width=2)
    draw.line([(cx, cy - cross), (cx, cy + cross)], fill=(248, 250, 252), width=2)

    try:
        font = ImageFont.load_default()
    except OSError:
        font = None

    label = f"{radius_miles:g} mi"
    if font:
        draw.text((margin + 4, margin + 2), label, fill=(203, 213, 225), font=font)

    for fl in flights:
        if not isinstance(fl, dict):
            continue
        lp = fl.get("last_position")
        if not isinstance(lp, dict):
            continue
        lat, lon = lp.get("latitude"), lp.get("longitude")
        if lat is None or lon is None:
            continue
        try:
            plat, plon = float(lat), float(lon)
        except (TypeError, ValueError):
            continue

        px, py = _lon_lat_to_xy(plon, plat, bbox, w, h, margin)
        r = 7
        draw.ellipse(
            [px - r, py - r, px + r, py + r],
            outline=(251, 191, 36),
            width=2,
        )
        draw.ellipse(
            [px - r + 1, py - r + 1, px + r - 1, py + r - 1],
            fill=(251, 191, 36),
        )

        hd = lp.get("heading")
        line = _heading_line(px, py, hd, length=18.0)
        if line:
            draw.line([line[0], line[1]], fill=(15, 23, 42), width=3)

        ident = fl.get("ident") or fl.get("fa_flight_id") or "?"
        if font and isinstance(ident, str):
            tx, ty = px + 10, py - 14
            # keep label inside frame
            tx = min(max(tx, margin), w - margin - 40)
            ty = min(max(ty, margin), h - margin - 12)
            draw.text((tx, ty), ident[:12], fill=(248, 250, 252), font=font)

    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()
