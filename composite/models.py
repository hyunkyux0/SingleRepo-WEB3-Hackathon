"""Models for the composite scoring system."""
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field


class OverrideEvent(BaseModel):
    """Record of a single override rule firing."""
    rule_id: str          # e.g. "O1a"
    tier: str             # "soft" or "hard"
    condition: str        # human-readable condition that triggered
    action: str           # what happened to the score
    score_before: float
    score_after: float


class CompositeScore(BaseModel):
    """Full composite scoring result for one asset."""
    asset: str
    technical_score: float = Field(ge=-1.0, le=1.0, default=0.0)
    derivatives_score: float = Field(ge=-1.0, le=1.0, default=0.0)
    on_chain_score: float = Field(ge=-1.0, le=1.0, default=0.0)
    mtf_score: float = Field(ge=-1.0, le=1.0, default=0.0)
    sentiment_score: float = Field(ge=-1.0, le=1.0, default=0.0)
    raw_composite: float = Field(ge=-1.0, le=1.0)
    final_score: float  # can exceed [-1,1] briefly before clamping in edge cases
    overrides_fired: list[OverrideEvent] = []
    decision: str = "HOLD"  # BUY, SELL, HOLD
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class TradingDecision(BaseModel):
    """Simplified output for the execution layer."""
    asset: str
    decision: str  # BUY, SELL, HOLD
    score: float
    confidence: float = 1.0
