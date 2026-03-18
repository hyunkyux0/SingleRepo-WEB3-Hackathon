"""Pydantic models for scored articles and aggregated sector signals.

Defines the data structures produced by the sentiment scoring and
signal aggregation pipeline.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class ScoredArticle(BaseModel):
    """Article with final sector + sentiment + computed weights."""

    article_id: str
    timestamp: datetime
    primary_sector: str
    sentiment: float  # -1.0 to 1.0
    magnitude: str  # "low", "medium", "high"
    source: str
    source_weight: float
    decay_weight: float = 1.0  # computed at query time


class SectorSignal(BaseModel):
    """Aggregated signal for a single sector."""

    sector: str
    sentiment: float  # weighted average, -1 to 1
    momentum: float  # rate of change vs lookback
    catalyst_active: bool = False
    catalyst_details: Optional[dict] = None
    article_count: int = 0
    confidence: float = 0.0  # scales with volume + LLM confidence


class SectorSignalSet(BaseModel):
    """Complete output: all sector signals at a point in time."""

    timestamp: datetime
    sectors: dict[str, SectorSignal]
    metadata: dict = Field(default_factory=dict)
