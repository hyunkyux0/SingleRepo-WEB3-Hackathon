"""Tests for derivatives data collectors with mocked HTTP."""
import pytest
from unittest.mock import patch, MagicMock
from derivatives.collectors import BinanceCollector, BybitCollector, CoinalyzeCollector


class TestBinanceCollector:
    def test_poll_interval(self):
        c = BinanceCollector()
        assert c.poll_interval_seconds() == 300

    @patch("derivatives.collectors.requests.get")
    def test_collect_funding_rates(self, mock_get):
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: [
                {"symbol": "BTCUSDT", "fundingRate": "0.00010000",
                 "fundingTime": 1710000000000, "markPrice": "65000.00"},
            ],
        )
        c = BinanceCollector()
        rows = c.collect_funding_rates(["BTC"])
        assert len(rows) == 1
        assert rows[0]["asset"] == "BTC"
        assert rows[0]["rate"] == 0.0001
        assert rows[0]["exchange"] == "binance"

    @patch("derivatives.collectors.requests.get")
    def test_collect_open_interest(self, mock_get):
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: {"symbol": "BTCUSDT", "openInterest": "12345.678",
                          "time": 1710000000000},
        )
        c = BinanceCollector()
        rows = c.collect_open_interest(["BTC"])
        assert len(rows) == 1
        assert rows[0]["oi_value"] == 12345.678

    @patch("derivatives.collectors.requests.get")
    def test_handles_api_error(self, mock_get):
        mock_get.side_effect = Exception("timeout")
        c = BinanceCollector()
        rows = c.collect_funding_rates(["BTC"])
        assert rows == []


class TestBybitCollector:
    @patch("derivatives.collectors.requests.get")
    def test_collect_funding_rates(self, mock_get):
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: {
                "retCode": 0,
                "result": {
                    "list": [
                        {"symbol": "BTCUSDT", "fundingRate": "0.000150",
                         "fundingRateTimestamp": "1710000000000"},
                    ]
                }
            },
        )
        c = BybitCollector()
        rows = c.collect_funding_rates(["BTC"])
        assert len(rows) == 1
        assert rows[0]["rate"] == 0.00015


class TestCoinalyzeCollector:
    @patch("derivatives.collectors.requests.get")
    def test_collect_long_short_ratio(self, mock_get):
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: [
                {"t": 1710000000, "o": 1.2, "h": 1.5, "l": 1.1, "c": 1.3},
            ],
        )
        c = CoinalyzeCollector(api_key="test_key")
        rows = c.collect_long_short_ratio(["BTC"])
        assert len(rows) == 1
        assert rows[0]["ratio"] == 1.3  # use close value
