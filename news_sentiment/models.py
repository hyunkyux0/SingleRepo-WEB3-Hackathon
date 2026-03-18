"""Pydantic models for the news sentiment pipeline.

Defines the normalised article schema consumed by processors and the
classification output schema returned by the LLM prompter.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class ArticleInput(BaseModel):
    """Normalized article from any source, ready for classification."""

    id: str
    timestamp: datetime
    source: str  # "cryptopanic", "rss_coindesk", "twitter", "reddit"
    headline: str
    body_snippet: str = ""
    url: str = ""
    mentioned_tickers: list[str] = Field(default_factory=list)
    source_sentiment: Optional[float] = None  # pre-existing score (CryptoPanic votes)
    relevance_score: float = 0.0
    is_catalyst: bool = False
    matched_sectors: list[str] = Field(default_factory=list)


class ClassificationOutput(BaseModel):
    """LLM classification result for a single article."""

    primary_sector: str
    secondary_sector: Optional[str] = None
    sentiment: float  # -1.0 to 1.0
    magnitude: str  # "low", "medium", "high"
    confidence: float = 0.0
    cross_market: bool = False
    reasoning: str = ""
