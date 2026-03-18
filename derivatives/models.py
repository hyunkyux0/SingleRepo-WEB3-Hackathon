"""Pydantic models for derivatives data and signals."""
from datetime import datetime
from pydantic import BaseModel, Field


class FundingSnapshot(BaseModel):
    """A single funding rate observation from one exchange.
    Rate is stored as a decimal fraction (0.01% = 0.0001)."""
    asset: str
    timestamp: datetime
    exchange: str
    rate: float


class OISnapshot(BaseModel):
    """Open interest snapshot from one exchange."""
    asset: str
    timestamp: datetime
    exchange: str
    oi_value: float  # in native units
    oi_usd: float    # in USD


class LongShortRatio(BaseModel):
    """Long/short ratio from an aggregator."""
    asset: str
    timestamp: datetime
    ratio: float
    source: str


class DerivativesSignal(BaseModel):
    """Combined derivatives signal for one asset."""
    asset: str
    funding_score: float = Field(ge=-1.0, le=1.0)
    oi_divergence_score: float = Field(ge=-1.0, le=1.0)
    long_short_score: float = Field(ge=-1.0, le=1.0)
    combined_score: float = Field(ge=-1.0, le=1.0)

    @classmethod
    def from_sub_scores(cls, asset: str, funding_score: float,
                        oi_divergence_score: float, long_short_score: float,
                        weights: dict) -> "DerivativesSignal":
        total_w = sum(weights.values())
        combined = (
            funding_score * weights["funding"]
            + oi_divergence_score * weights["oi_divergence"]
            + long_short_score * weights["long_short"]
        ) / total_w
        combined = max(-1.0, min(1.0, combined))
        return cls(asset=asset, funding_score=funding_score,
                   oi_divergence_score=oi_divergence_score,
                   long_short_score=long_short_score,
                   combined_score=combined)
