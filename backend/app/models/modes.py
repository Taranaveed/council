from typing import Any, Optional



from pydantic import BaseModel, Field





class SellerEconomics(BaseModel):

    """Optional cost / positioning inputs shared by seller tools."""



    cost_of_goods: Optional[str] = None

    target_margin_pct: Optional[str] = None

    condition: Optional[str] = None

    category: Optional[str] = None

    competitor_links: Optional[str] = None





class PriceBargainingRequest(SellerEconomics):

    product_specs: str = Field(min_length=3)

    price_range_min: str

    price_range_max: str

    currency: str = "USD"

    location: Optional[str] = None

    product_name: Optional[str] = None

    problem_solved: Optional[str] = None





class PriceBargainingResponse(BaseModel):

    transcript: dict[str, str]

    verdict: dict[str, Any]

    market_listings: list[dict[str, Any]] = []

    market_warning: Optional[str] = None

    raw_verdict: Optional[str] = None

    price_explanation: Optional[dict[str, Any]] = None

    action_pack: Optional[dict[str, Any]] = None

    empty_state_note: Optional[str] = None





class AudienceDiscoveryRequest(SellerEconomics):

    product_name: str = Field(min_length=2)

    problem_solved: str = Field(min_length=3)

    location: Optional[str] = None

    currency: str = "USD"

    price_range_min: Optional[str] = None

    price_range_max: Optional[str] = None

    product_specs: Optional[str] = None





class AudienceDiscoveryResponse(BaseModel):

    transcript: dict[str, str]

    verdict: dict[str, Any]

    market_listings: list[dict[str, Any]] = []

    market_warning: Optional[str] = None

    raw_verdict: Optional[str] = None

    channel_creatives: list[dict[str, Any]] = []

    action_pack: Optional[dict[str, Any]] = None

    empty_state_note: Optional[str] = None





class LaunchPackRequest(SellerEconomics):

    product_name: str = Field(min_length=2)

    product_specs: str = Field(min_length=3)

    problem_solved: str = Field(min_length=3)

    price_range_min: str

    price_range_max: str

    currency: str = "USD"

    location: Optional[str] = None

    # Optional second SKU for side-by-side compare

    variant_b_name: Optional[str] = None

    variant_b_specs: Optional[str] = None





class LaunchPackVariantResult(BaseModel):

    label: str

    product_name: str

    price_verdict: dict[str, Any] = {}

    audience_verdict: dict[str, Any] = {}

    price_transcript: dict[str, str] = {}

    audience_transcript: dict[str, str] = {}

    price_explanation: dict[str, Any] = {}

    action_pack: dict[str, Any] = {}

    channel_creatives: list[dict[str, Any]] = []

    export_text: str = ""

    empty_state_note: Optional[str] = None

    market_listings: list[dict[str, Any]] = []

    market_warning: Optional[str] = None





class LaunchPackResponse(BaseModel):

    primary: LaunchPackVariantResult

    variant_b: Optional[LaunchPackVariantResult] = None

    comparison_note: Optional[str] = None

    market_listings: list[dict[str, Any]] = []

    market_warning: Optional[str] = None





class DealFinderRequest(BaseModel):

    item_name: str = Field(min_length=2)

    location: str = Field(min_length=2)

    max_budget: Optional[str] = None

    marketplace: str = "local_retailers"

    quantity: Optional[int] = Field(default=None, ge=1, le=100000)

    buying_mode: str = Field(default="retail")  # retail | bulk





class DealFinderResponse(BaseModel):

    transcript: dict[str, str]

    verdict: dict[str, Any]

    market_listings: list[dict[str, Any]] = []

    market_warning: Optional[str] = None

    raw_verdict: Optional[str] = None

    risk_score: Optional[dict[str, Any]] = None

    negotiation_script: list[str] = []

    buy_checklist: list[str] = []


