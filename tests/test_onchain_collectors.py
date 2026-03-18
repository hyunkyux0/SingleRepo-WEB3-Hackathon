# tests/test_onchain_collectors.py
import pytest
from unittest.mock import patch, MagicMock
from on_chain.collectors import CoinMetricsCollector, EtherscanCollector


class TestCoinMetricsCollector:
    @patch("on_chain.collectors.requests.get")
    def test_collect_daily(self, mock_get):
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: {
                "data": [
                    {
                        "asset": "btc",
                        "time": "2026-03-18T00:00:00.000000000Z",
                        "FlowInExNtv": "500.0",
                        "FlowOutExNtv": "300.0",
                        "AdrActCnt": "900000",
                        "CapMVRVCur": "2.5",
                    }
                ]
            },
        )
        c = CoinMetricsCollector()
        rows = c.collect(["BTC"])
        assert len(rows) == 1
        assert rows[0]["asset"] == "BTC"
        assert rows[0]["mvrv"] == 2.5
        assert abs(rows[0]["nupl_computed"] - 0.6) < 0.01

    @patch("on_chain.collectors.requests.get")
    def test_missing_asset_returns_empty(self, mock_get):
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: {"data": []},
        )
        c = CoinMetricsCollector()
        rows = c.collect(["SOMI"])
        assert rows == []


class TestEtherscanCollector:
    @patch("on_chain.collectors.requests.get")
    def test_collect_whale_transfers(self, mock_get):
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: {
                "status": "1",
                "result": [
                    {
                        "hash": "0xabc123",
                        "from": "0xsender",
                        "to": "0xbinance_hot_wallet",
                        "value": "2000000000000000000000",  # 2000 ETH
                        "timeStamp": "1710720000",
                        "tokenSymbol": "ETH",
                        "tokenDecimal": "18",
                    }
                ],
            },
        )
        c = EtherscanCollector(
            api_key="test",
            exchange_addresses={"0xbinance_hot_wallet": "binance"},
            eth_price_usd=3000.0,
        )
        rows = c.collect_whale_transfers(min_value_usd=1000000)
        assert len(rows) == 1
        assert rows[0]["direction"] == "to_exchange"
