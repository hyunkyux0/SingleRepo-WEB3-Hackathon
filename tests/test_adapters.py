"""Tests for composite/adapters.py — signal-to-asset mapping."""

import json
from datetime import datetime, timezone

import pytest

from composite.adapters import sector_signal_to_asset_score
from sentiment_score.models import SectorSignal, SectorSignalSet


NOW = datetime.now(tz=timezone.utc)


@pytest.fixture
def sector_map():
    with open("config/sector_map.json") as f:
        return json.load(f)


@pytest.fixture
def signal_set():
    return SectorSignalSet(
        timestamp=NOW,
        sectors={
            "ai_compute": SectorSignal(
                sector="ai_compute", sentiment=0.8, momentum=0.3,
                article_count=5, confidence=0.9, catalyst_active=True,
                catalyst_details={"article_id": "x"},
            ),
            "defi": SectorSignal(
                sector="defi", sentiment=-0.2, momentum=-0.1,
                article_count=3, confidence=0.6,
            ),
            "l1_infra": SectorSignal(
                sector="l1_infra", sentiment=0.1, momentum=0.0,
                article_count=2, confidence=0.3,
            ),
            "meme": SectorSignal(sector="meme", sentiment=0.0, momentum=0.0),
            "store_of_value": SectorSignal(sector="store_of_value", sentiment=0.0, momentum=0.0),
            "other": SectorSignal(sector="other", sentiment=0.0, momentum=0.0),
        },
    )


class TestSectorSignalToAssetScore:
    def test_primary_sector_mapping(self, sector_map, signal_set):
        score = sector_signal_to_asset_score("FET/USD", signal_set, sector_map)
        assert score["sentiment"] == 0.8
        assert score["sector"] == "ai_compute"
        assert score["catalyst_active"] is True

    def test_defi_token(self, sector_map, signal_set):
        score = sector_signal_to_asset_score("AAVE/USD", signal_set, sector_map)
        assert score["sentiment"] == -0.2
        assert score["sector"] == "defi"
        assert score["catalyst_active"] is False

    def test_dual_routed_near(self, sector_map, signal_set):
        score = sector_signal_to_asset_score("NEAR/USD", signal_set, sector_map)
        # NEAR: primary l1_infra (0.1), secondary ai_compute
        assert score["primary_sentiment"] == 0.1
        assert score["secondary_sentiment"] == 0.8 * 0.5  # 50% weight
        assert score["sector"] == "l1_infra"
        # ai_compute has catalyst, l1_infra doesn't → propagated
        assert score["catalyst_active"] is True

    def test_dual_routed_btc(self, sector_map, signal_set):
        score = sector_signal_to_asset_score("BTC/USD", signal_set, sector_map)
        # BTC: primary l1_infra, secondary store_of_value
        assert score["primary_sentiment"] == 0.1
        assert score["secondary_sentiment"] == 0.0 * 0.5  # store_of_value = 0.0

    def test_token_not_in_map(self, signal_set):
        score = sector_signal_to_asset_score("UNKNOWN/USD", signal_set, {})
        assert score["sentiment"] == 0.0
        assert score["sector"] == "other"
        assert score["catalyst_active"] is False

    def test_returns_all_required_fields(self, sector_map, signal_set):
        score = sector_signal_to_asset_score("DOGE/USD", signal_set, sector_map)
        required = {"sentiment", "momentum", "confidence", "sector",
                     "catalyst_active", "primary_sentiment", "secondary_sentiment"}
        assert required.issubset(score.keys())

    def test_meme_token(self, sector_map, signal_set):
        score = sector_signal_to_asset_score("PEPE/USD", signal_set, sector_map)
        assert score["sector"] == "meme"
        assert score["sentiment"] == 0.0

    def test_no_secondary_for_single_sector_token(self, sector_map, signal_set):
        score = sector_signal_to_asset_score("AAVE/USD", signal_set, sector_map)
        assert score["secondary_sentiment"] is None

    def test_catalyst_not_propagated_when_primary_already_active(self, sector_map):
        # Both sectors have catalysts — primary takes precedence
        signal_set = SectorSignalSet(
            timestamp=NOW,
            sectors={
                "l1_infra": SectorSignal(
                    sector="l1_infra", sentiment=0.5, momentum=0.1,
                    catalyst_active=True,
                ),
                "ai_compute": SectorSignal(
                    sector="ai_compute", sentiment=0.8, momentum=0.3,
                    catalyst_active=True,
                ),
                "defi": SectorSignal(sector="defi", sentiment=0.0, momentum=0.0),
                "meme": SectorSignal(sector="meme", sentiment=0.0, momentum=0.0),
                "store_of_value": SectorSignal(sector="store_of_value", sentiment=0.0, momentum=0.0),
                "other": SectorSignal(sector="other", sentiment=0.0, momentum=0.0),
            },
        )
        score = sector_signal_to_asset_score("NEAR/USD", signal_set, sector_map)
        assert score["catalyst_active"] is True  # from primary
