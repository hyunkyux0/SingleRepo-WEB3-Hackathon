"""Adapter to convert SectorSignalSet into per-asset sentiment scores.

Maps each asset to its sector(s) via the sector map, then extracts
the relevant sector signal. For dual-routed tokens, the secondary
sector signal is included at 50% weight.
"""

from __future__ import annotations

import logging
from typing import Any

from sentiment_score.models import SectorSignalSet

logger = logging.getLogger(__name__)


def sector_signal_to_asset_score(
    asset: str,
    signal_set: SectorSignalSet,
    sector_map: dict[str, Any],
) -> dict[str, Any]:
    """Convert a sector-level signal set into a per-asset sentiment score.

    Args:
        asset: Asset identifier (e.g. ``"FET/USD"``).
        signal_set: The current sector signal set.
        sector_map: Parsed ``config/sector_map.json``.

    Returns:
        A dict with keys: ``sentiment``, ``momentum``, ``confidence``,
        ``sector``, ``catalyst_active``, ``primary_sentiment``,
        ``secondary_sentiment``.
    """
    mapping = sector_map.get(asset, {})
    primary = mapping.get("primary", "other")
    secondary = mapping.get("secondary")

    primary_signal = signal_set.sectors.get(primary)
    if primary_signal is None:
        return {
            "sentiment": 0.0,
            "momentum": 0.0,
            "confidence": 0.0,
            "sector": "other",
            "catalyst_active": False,
            "primary_sentiment": 0.0,
            "secondary_sentiment": None,
        }

    result = {
        "sentiment": primary_signal.sentiment,
        "momentum": primary_signal.momentum,
        "confidence": primary_signal.confidence,
        "sector": primary,
        "catalyst_active": primary_signal.catalyst_active,
        "primary_sentiment": primary_signal.sentiment,
        "secondary_sentiment": None,
    }

    # Dual-routing: include secondary sector signal at 50% weight
    if secondary:
        secondary_signal = signal_set.sectors.get(secondary)
        if secondary_signal:
            result["secondary_sentiment"] = secondary_signal.sentiment * 0.5
            # If secondary has a catalyst, propagate it
            if secondary_signal.catalyst_active and not primary_signal.catalyst_active:
                result["catalyst_active"] = True

    return result
