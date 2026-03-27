#!/usr/bin/env python3
"""Fetch nearby flights from the running API, then save the rendered map PNG."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from urllib.parse import urljoin

import httpx


def _pop_verbose_flags(argv: list[str]) -> tuple[bool, list[str]]:
    """Accept -v / --verbose anywhere; keeps argparse from rejecting unknown -v."""
    verbose = False
    rest: list[str] = []
    for a in argv:
        if a in ("-v", "--verbose"):
            verbose = True
        else:
            rest.append(a)
    return verbose, rest


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]
    verbose_cli, argv = _pop_verbose_flags(argv)

    p = argparse.ArgumentParser(
        description="GET /api/flights/near, then POST the result to /api/flights/near/image.",
        epilog="Tip: pass -v or --verbose anywhere for flight idents and page count on stderr.",
    )
    p.add_argument("--lat", type=float, required=True, help="Center latitude (WGS84)")
    p.add_argument("--lon", type=float, required=True, help="Center longitude (WGS84)")
    p.add_argument(
        "--radius-miles",
        type=float,
        default=1.0,
        help="Search radius in statute miles (default: 1.0)",
    )
    p.add_argument(
        "--adsb-only",
        action="store_true",
        help="Use ADS-B positions search only",
    )
    p.add_argument(
        "--no-strict-circle",
        action="store_true",
        help="Keep flights outside the circle if the bbox matched",
    )
    p.add_argument(
        "--max-pages",
        type=int,
        default=1,
        help="Max AeroAPI pages (default: 1)",
    )
    p.add_argument(
        "--base-url",
        default="http://127.0.0.1:8000",
        help="API root URL (default: http://127.0.0.1:8000)",
    )
    p.add_argument(
        "-o",
        "--output",
        default="map.png",
        help="Output PNG path (default: map.png)",
    )
    p.add_argument(
        "--width",
        type=int,
        default=900,
        help="Map image size in pixels (default: 900)",
    )
    args = p.parse_args(argv)

    base = args.base_url.rstrip("/") + "/"
    near_url = urljoin(base, "api/flights/near")
    params = {
        "lat": args.lat,
        "lon": args.lon,
        "radius_miles": args.radius_miles,
        "adsb_only": args.adsb_only,
        "strict_circle": not args.no_strict_circle,
        "max_pages": args.max_pages,
    }

    try:
        with httpx.Client(timeout=60.0) as client:
            r1 = client.get(near_url, params=params)
            r1.raise_for_status()
            payload = r1.json()

            flights = payload.get("flights") if isinstance(payload, dict) else None
            n = len(flights) if isinstance(flights, list) else 0
            print(f"Nearby flights returned: {n}", file=sys.stderr)
            if verbose_cli and isinstance(payload, dict):
                pages = payload.get("num_pages_fetched")
                if pages is not None:
                    print(f"AeroAPI pages fetched: {pages}", file=sys.stderr)
                if isinstance(flights, list) and flights:
                    idents = []
                    for f in flights:
                        if isinstance(f, dict) and f.get("ident"):
                            idents.append(str(f["ident"]))
                        elif isinstance(f, dict) and f.get("fa_flight_id"):
                            idents.append(str(f["fa_flight_id"]))
                    if idents:
                        print(f"Idents: {', '.join(idents)}", file=sys.stderr)

            img_url = urljoin(base, "api/flights/near/image")
            r2 = client.post(
                img_url,
                params={"width": args.width},
                json=payload,
            )
            r2.raise_for_status()
    except httpx.HTTPStatusError as e:
        detail = ""
        try:
            detail = e.response.text[:500]
        except Exception:
            pass
        print(f"HTTP {e.response.status_code}: {e.request.url!s}", file=sys.stderr)
        if detail:
            print(detail, file=sys.stderr)
        return 1
    except httpx.RequestError as e:
        print(str(e), file=sys.stderr)
        return 1

    out = Path(args.output)
    out.write_bytes(r2.content)
    print(f"Wrote {out.resolve()} ({len(r2.content)} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(None))
