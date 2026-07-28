from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from app.core.auth import get_current_user
from app.db.marketplaces import (
    get_marketplace_by_slug,
    infer_location_context,
    list_marketplaces_for_location,
)

router = APIRouter(prefix="/api/marketplaces", tags=["marketplaces"])


class MarketplaceOut(BaseModel):
    slug: str
    name: str
    currency: Optional[str] = None
    safety_guidelines: str
    regulatory_notes: str
    hint: str
    sort_order: int = 100


class MarketplaceListResponse(BaseModel):
    location: str
    location_context: dict
    marketplaces: list[MarketplaceOut]


@router.get("/by-location", response_model=MarketplaceListResponse)
def get_marketplaces_for_location(
    location: str = Query(..., min_length=2),
    country_code: str | None = Query(None, min_length=2, max_length=2),
    _user: dict = Depends(get_current_user),
):
    profiles = list_marketplaces_for_location(location, country_code=country_code)
    ctx = infer_location_context(location if not country_code else f"{location} {country_code}")
    marketplaces = [
        MarketplaceOut(
            slug=p["slug"],
            name=p["name"],
            currency=p.get("currency"),
            safety_guidelines=p["safety_guidelines"],
            regulatory_notes=p["regulatory_notes"],
            hint=p.get("hint") or "",
            sort_order=p.get("sort_order", 100),
        )
        for p in profiles
    ]
    return MarketplaceListResponse(
        location=location,
        location_context=ctx,
        marketplaces=marketplaces,
    )


@router.get("/profile/{slug}", response_model=MarketplaceOut)
def get_marketplace(
    slug: str,
    _user: dict = Depends(get_current_user),
):
    profile = get_marketplace_by_slug(slug)
    if not profile:
        raise HTTPException(status_code=404, detail="Marketplace not found")
    return MarketplaceOut(
        slug=profile["slug"],
        name=profile["name"],
        currency=profile.get("currency"),
        safety_guidelines=profile["safety_guidelines"],
        regulatory_notes=profile["regulatory_notes"],
        hint=profile.get("hint") or "",
        sort_order=profile.get("sort_order", 100),
    )
