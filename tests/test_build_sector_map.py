"""Tests for scripts/build_sector_map.py — CoinGecko sector map builder."""

from unittest.mock import patch

import pytest

from scripts.build_sector_map import (
    CATEGORY_TO_SECTOR,
    DUAL_ROUTE_OVERRIDES,
    classify_token,
    build_sector_map,
)


# ═════════════════════════════════════════════════════════════════════════
# Category mapping
# ═════════════════════════════════════════════════════════════════════════


class TestCategoryToSector:
    def test_ai_categories(self):
        assert CATEGORY_TO_SECTOR["artificial-intelligence"] == "ai_compute"
        assert CATEGORY_TO_SECTOR["ai-agents"] == "ai_compute"

    def test_defi_categories(self):
        assert CATEGORY_TO_SECTOR["decentralized-finance-defi"] == "defi"
        assert CATEGORY_TO_SECTOR["lending-borrowing"] == "defi"
        assert CATEGORY_TO_SECTOR["oracle"] == "defi"

    def test_l1_categories(self):
        assert CATEGORY_TO_SECTOR["layer-1"] == "l1_infra"
        assert CATEGORY_TO_SECTOR["layer-2"] == "l1_infra"

    def test_meme_categories(self):
        assert CATEGORY_TO_SECTOR["meme-token"] == "meme"
        assert CATEGORY_TO_SECTOR["dog-themed-coins"] == "meme"

    def test_store_of_value_categories(self):
        assert CATEGORY_TO_SECTOR["store-of-value"] == "store_of_value"
        assert CATEGORY_TO_SECTOR["privacy-coins"] == "store_of_value"

    def test_dual_route_overrides(self):
        assert DUAL_ROUTE_OVERRIDES["NEAR"] == "ai_compute"
        assert DUAL_ROUTE_OVERRIDES["BTC"] == "store_of_value"


# ═════════════════════════════════════════════════════════════════════════
# classify_token
# ═════════════════════════════════════════════════════════════════════════


class TestClassifyToken:
    def test_single_known_category(self):
        result = classify_token("FET", ["artificial-intelligence"])
        assert result["primary"] == "ai_compute"
        assert result["secondary"] is None

    def test_multiple_categories_first_wins(self):
        result = classify_token("TEST", ["decentralized-finance-defi", "layer-1"])
        assert result["primary"] == "defi"

    def test_no_categories_defaults_to_other(self):
        result = classify_token("UNKNOWN", [])
        assert result["primary"] == "other"
        assert result["secondary"] is None

    def test_unknown_categories_default_to_other(self):
        result = classify_token("X", ["gaming", "metaverse"])
        assert result["primary"] == "other"

    def test_dual_route_override_near(self):
        result = classify_token("NEAR", ["layer-1"])
        assert result["primary"] == "l1_infra"
        assert result["secondary"] == "ai_compute"

    def test_dual_route_override_btc(self):
        result = classify_token("BTC", ["layer-1"])
        assert result["primary"] == "l1_infra"
        assert result["secondary"] == "store_of_value"

    def test_secondary_suppressed_when_same_as_primary(self):
        # If BTC's primary is already store_of_value, secondary should be None
        result = classify_token("BTC", ["store-of-value"])
        assert result["primary"] == "store_of_value"
        assert result["secondary"] is None

    def test_returns_correct_shape(self):
        result = classify_token("ETH", ["layer-1", "smart-contract-platform"])
        assert "primary" in result
        assert "secondary" in result


# ═════════════════════════════════════════════════════════════════════════
# build_sector_map
# ═════════════════════════════════════════════════════════════════════════


class TestBuildSectorMap:
    @patch("scripts.build_sector_map._fetch_coingecko_categories")
    def test_produces_valid_map(self, mock_fetch):
        mock_fetch.return_value = {
            "FET": ["artificial-intelligence"],
            "BTC": ["layer-1", "store-of-value"],
        }
        result = build_sector_map(["FET/USD", "BTC/USD"])
        assert "FET/USD" in result
        assert "BTC/USD" in result
        assert result["FET/USD"]["primary"] == "ai_compute"
        assert result["BTC/USD"]["primary"] == "l1_infra"

    @patch("scripts.build_sector_map._fetch_coingecko_categories")
    def test_unknown_token_gets_other(self, mock_fetch):
        mock_fetch.return_value = {}
        result = build_sector_map(["UNKNOWN/USD"])
        assert result["UNKNOWN/USD"]["primary"] == "other"

    @patch("scripts.build_sector_map._fetch_coingecko_categories")
    def test_all_universe_tokens_mapped(self, mock_fetch):
        mock_fetch.return_value = {}  # all unknown
        universe = ["A/USD", "B/USD", "C/USD"]
        result = build_sector_map(universe)
        assert len(result) == 3
        for pair in universe:
            assert pair in result

    @patch("scripts.build_sector_map._fetch_coingecko_categories")
    def test_dual_routing_preserved(self, mock_fetch):
        mock_fetch.return_value = {
            "NEAR": ["layer-1", "artificial-intelligence"],
        }
        result = build_sector_map(["NEAR/USD"])
        assert result["NEAR/USD"]["primary"] == "l1_infra"
        assert result["NEAR/USD"]["secondary"] == "ai_compute"
