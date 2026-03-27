"""HTTP client for FlightAware AeroAPI flight search endpoints."""

from __future__ import annotations

import urllib.parse
from typing import Any

import httpx

from app.config import Settings
from app.geo import BoundingBox


class AeroAPIError(Exception):
    """Raised when AeroAPI returns an error response."""

    def __init__(self, status_code: int, detail: str):
        self.status_code = status_code
        self.detail = detail
        super().__init__(detail)


def _build_latlong_query(box: BoundingBox) -> str:
    # Order per AeroAPI: MINLAT MINLON MAXLAT MAXLON
    return (
        f'-latlong "{box.min_lat} {box.min_lon} {box.max_lat} {box.max_lon}"'
    )


def _build_positions_adsb_query(box: BoundingBox) -> str:
    # Curly-brace syntax; ranges are numeric inclusive on lat/lon; A = ADS-B
    return (
        f"{{range lat {box.min_lat} {box.max_lat}}} "
        f"{{range lon {box.min_lon} {box.max_lon}}} "
        "{= updateType A}"
    )


async def search_flights_in_box(
    settings: Settings,
    box: BoundingBox,
    *,
    max_pages: int,
) -> list[dict[str, Any]]:
    """GET /flights/search with simplified -latlong query; follows pagination."""
    query = _build_latlong_query(box)
    return await _fetch_paged(
        settings,
        "/flights/search",
        {"query": query},
        max_pages,
        collection_key="flights",
    )


async def search_positions_adsb_in_box(
    settings: Settings,
    box: BoundingBox,
    *,
    max_pages: int,
) -> list[dict[str, Any]]:
    """GET /flights/search/positions filtered to ADS-B positions in the box."""
    query = _build_positions_adsb_query(box)
    return await _fetch_paged(
        settings,
        "/flights/search/positions",
        {"query": query, "unique_flights": "true"},
        max_pages,
        collection_key="positions",
    )


def _next_request_url(settings: Settings, links: dict[str, Any] | None) -> str | None:
    if not links:
        return None
    nxt = links.get("next")
    if not nxt or not isinstance(nxt, str):
        return None
    base = settings.aeroapi_base_url.rstrip("/")
    if nxt.startswith("http://") or nxt.startswith("https://"):
        return nxt
    path = nxt if nxt.startswith("/") else f"/{nxt}"
    # AeroAPI next links are typically under /aeroapi/...
    if path.startswith("/aeroapi"):
        origin = urllib.parse.urlparse(settings.aeroapi_base_url)
        return f"{origin.scheme}://{origin.netloc}{path}"
    return f"{base}{path}"


async def _fetch_paged(
    settings: Settings,
    path: str,
    params: dict[str, str],
    max_pages: int,
    *,
    collection_key: str,
) -> list[dict[str, Any]]:
    base = settings.aeroapi_base_url.rstrip("/")
    url = f"{base}{path}"
    headers = {"x-apikey": settings.aeroapi_api_key}

    out: list[dict[str, Any]] = []
    page = 0
    next_url: str | None = url
    next_params: dict[str, str] | None = {**params, "max_pages": "1"}

    async with httpx.AsyncClient(timeout=60.0) as client:
        while next_url and page < max_pages:
            if next_params is not None:
                resp = await client.get(next_url, params=next_params, headers=headers)
            else:
                resp = await client.get(next_url, headers=headers)

            if resp.status_code >= 400:
                try:
                    err = resp.json()
                    detail = str(err.get("detail", err.get("title", resp.text)))
                except Exception:
                    detail = resp.text or resp.reason_phrase
                raise AeroAPIError(resp.status_code, detail)

            data = resp.json()
            batch = data.get(collection_key)
            if isinstance(batch, list):
                out.extend(batch)

            page += 1
            links = data.get("links") if isinstance(data.get("links"), dict) else None
            resolved = _next_request_url(settings, links)
            if resolved and resolved != next_url:
                next_url = resolved
                next_params = None
            else:
                next_url = None
                next_params = None

    return out
