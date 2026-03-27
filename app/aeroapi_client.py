"""Async client for FlightAware AeroAPI flight search endpoints."""

from __future__ import annotations

from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx

from app.geo import BoundingBox

_DEFAULT_TIMEOUT = httpx.Timeout(30.0)


def _format_latlon_query(bbox: BoundingBox) -> str:
    """Build simplified `-latlong` query segment for GET /flights/search."""
    return (
        f'-latlong "{bbox.min_lat} {bbox.min_lon} {bbox.max_lat} {bbox.max_lon}"'
    )


def _format_positions_query(bbox: BoundingBox) -> str:
    """Build `{range ...}` query for GET /flights/search/positions (ADS-B only)."""
    return (
        f"{{range lat {bbox.min_lat} {bbox.max_lat}}} "
        f"{{range lon {bbox.min_lon} {bbox.max_lon}}} "
        "{= updateType A}"
    )


def _cursor_from_next_link(next_url: str | None) -> str | None:
    if not next_url:
        return None
    parsed = urlparse(next_url)
    qs = parse_qs(parsed.query)
    cur = qs.get("cursor", [None])[0]
    return cur


async def _collect_flights_search(
    client: httpx.AsyncClient,
    base_url: str,
    api_key: str,
    query: str,
    max_pages: int,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Pages through /flights/search until max_pages or no next link."""
    all_flights: list[dict[str, Any]] = []
    meta: dict[str, Any] = {}
    cursor: str | None = None
    pages_done = 0

    while pages_done < max_pages:
        params: dict[str, Any] = {
            "query": query,
            "max_pages": 1,
        }
        if cursor:
            params["cursor"] = cursor

        r = await client.get(
            f"{base_url.rstrip('/')}/flights/search",
            params=params,
            headers={"x-apikey": api_key},
        )
        if r.status_code >= 400:
            raise AeroAPIError(r.status_code, _safe_error_body(r))

        data = r.json()
        meta.setdefault("num_pages_total", 0)
        meta["num_pages_total"] = meta.get("num_pages_total", 0) + int(
            data.get("num_pages") or 0
        )
        batch = data.get("flights") or []
        all_flights.extend(batch)
        pages_done += 1

        links = data.get("links") or {}
        next_link = links.get("next") if isinstance(links, dict) else None
        cursor = _cursor_from_next_link(next_link)
        if not cursor:
            break

    return all_flights, meta


async def _collect_positions_search(
    client: httpx.AsyncClient,
    base_url: str,
    api_key: str,
    query: str,
    max_pages: int,
    unique_flights: bool,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    all_positions: list[dict[str, Any]] = []
    meta: dict[str, Any] = {}
    cursor: str | None = None
    pages_done = 0

    while pages_done < max_pages:
        params: dict[str, Any] = {
            "query": query,
            "max_pages": 1,
            "unique_flights": unique_flights,
        }
        if cursor:
            params["cursor"] = cursor

        r = await client.get(
            f"{base_url.rstrip('/')}/flights/search/positions",
            params=params,
            headers={"x-apikey": api_key},
        )
        if r.status_code >= 400:
            raise AeroAPIError(r.status_code, _safe_error_body(r))

        data = r.json()
        meta.setdefault("num_pages_total", 0)
        meta["num_pages_total"] = meta.get("num_pages_total", 0) + int(
            data.get("num_pages") or 0
        )
        batch = data.get("positions") or []
        all_positions.extend(batch)
        pages_done += 1

        links = data.get("links") or {}
        next_link = links.get("next") if isinstance(links, dict) else None
        cursor = _cursor_from_next_link(next_link)
        if not cursor:
            break

    return all_positions, meta


class AeroAPIError(Exception):
    def __init__(self, status_code: int, body: Any):
        self.status_code = status_code
        self.body = body
        super().__init__(f"AeroAPI error {status_code}: {body}")


def _safe_error_body(response: httpx.Response) -> Any:
    try:
        return response.json()
    except Exception:
        return response.text


async def search_flights_near(
    *,
    base_url: str,
    api_key: str,
    bbox: BoundingBox,
    max_pages: int,
    adsb_only: bool,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """
    Query AeroAPI for flights or positions inside the bounding box.

    When ``adsb_only`` is True, uses ``/flights/search/positions`` with
    ``updateType A`` (ADS-B). Otherwise uses ``/flights/search`` with ``-latlong``.
    """
    async with httpx.AsyncClient(timeout=_DEFAULT_TIMEOUT) as client:
        if adsb_only:
            q = _format_positions_query(bbox)
            return await _collect_positions_search(
                client,
                base_url,
                api_key,
                q,
                max_pages,
                unique_flights=True,
            )
        q = _format_latlon_query(bbox)
        return await _collect_flights_search(client, base_url, api_key, q, max_pages)
