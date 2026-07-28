"""IP geolocation + nearest-region hints (CDN / multi-region aware)."""
from __future__ import annotations

import os
from typing import Optional

import httpx
from fastapi import APIRouter, Request
from pydantic import BaseModel

router = APIRouter(prefix="/api/geo", tags=["geo"])

# Map ISO country codes → app region labels used for marketplace + API routing
COUNTRY_TO_REGION = {
    "PK": "asia",
    "IN": "asia",
    "BD": "asia",
    "AE": "asia",
    "SG": "asia",
    "GB": "eu",
    "IE": "eu",
    "DE": "eu",
    "FR": "eu",
    "ES": "eu",
    "IT": "eu",
    "NL": "eu",
    "BE": "eu",
    "PT": "eu",
    "AT": "eu",
    "SE": "eu",
    "PL": "eu",
    "US": "us",
    "CA": "us",
    "MX": "us",
}

COUNTRY_NAMES = {
    "PK": "Pakistan",
    "GB": "United Kingdom",
    "US": "United States",
    "DE": "Germany",
    "FR": "France",
    "IE": "Ireland",
    "CA": "Canada",
    "IN": "India",
    "AE": "United Arab Emirates",
    "SG": "Singapore",
    "NL": "Netherlands",
    "ES": "Spain",
    "IT": "Italy",
}


class GeoResponse(BaseModel):
    ip: Optional[str] = None
    city: Optional[str] = None
    region: Optional[str] = None
    country: Optional[str] = None
    country_code: Optional[str] = None
    location_label: str
    nearest_api_region: str
    source: str


def _client_ip(request: Request) -> Optional[str]:
    # Cloudflare / common reverse-proxy headers
    for header in (
        "cf-connecting-ip",
        "true-client-ip",
        "x-real-ip",
        "x-forwarded-for",
    ):
        raw = request.headers.get(header)
        if raw:
            return raw.split(",")[0].strip()
    if request.client:
        return request.client.host
    return None


async def _lookup_ip_api(ip: Optional[str]) -> dict:
    """Use ipapi.co (no key required for light use)."""
    url = f"https://ipapi.co/{ip}/json/" if ip and ip not in ("127.0.0.1", "::1") else "https://ipapi.co/json/"
    async with httpx.AsyncClient(timeout=8.0) as client:
        res = await client.get(url, headers={"User-Agent": "synthetic-focus-group/1.0"})
        res.raise_for_status()
        return res.json()


@router.get("/ip", response_model=GeoResponse)
async def resolve_ip_location(request: Request):
    """
    Prefill location from IP.
    Prefer Cloudflare CF-IPCountry when traffic is fronted by a global CDN/load balancer.
    """
    ip = _client_ip(request)
    cf_country = (request.headers.get("cf-ipcountry") or "").upper().strip()
    if cf_country in ("", "XX", "T1"):
        cf_country = ""

    city = region = country = None
    country_code = cf_country or None
    source = "cloudflare" if cf_country else "ipapi"

    try:
        data = await _lookup_ip_api(ip)
        city = data.get("city")
        region = data.get("region") or data.get("region_code")
        country = data.get("country_name") or data.get("country")
        api_cc = (data.get("country_code") or "").upper()
        if len(api_cc) == 2 and not country_code:
            country_code = api_cc
            source = "ipapi"
        elif len(api_cc) == 2 and country_code:
            # Keep CF country for routing, still use IP API for city label
            source = "cloudflare+ipapi"
        if data.get("error") and not country_code:
            source = "fallback"
    except Exception as e:
        print(f"[geo] ip lookup failed: {e}")
        if not country_code:
            source = "fallback"

    fallback_cc = (os.getenv("DEFAULT_COUNTRY_CODE") or "US").upper()
    country_code = (country_code or fallback_cc).upper()
    if len(country_code) != 2:
        country_code = fallback_cc if len(fallback_cc) == 2 else "US"
    country = country or COUNTRY_NAMES.get(country_code, country_code)
    parts = [p for p in [city, country] if p]
    location_label = ", ".join(parts) if parts else country

    nearest = COUNTRY_TO_REGION.get(
        country_code,
        os.getenv("DEFAULT_REGION", "us").lower(),
    )

    return GeoResponse(
        ip=ip,
        city=city,
        region=region,
        country=country,
        country_code=country_code,
        location_label=location_label,
        nearest_api_region=nearest,
        source=source,
    )
