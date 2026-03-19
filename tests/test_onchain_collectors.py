# tests/test_onchain_collectors.py
import pytest
from unittest.mock import patch, MagicMock
from on_chain.collectors import CoinMetricsCollector, EtherscanCollector


def _catalog_response(assets_with_metrics):
    """Build a mock catalog response. assets_with_metrics: list of (asset_id, metric_list)."""
    return MagicMock(
        status_code=200,
        json=lambda: {
            "data": [
                {"asset": aid, "metrics": [{"metric": m} for m in metrics]}
                for aid, metrics in assets_with_metrics
            ]
        },
        raise_for_status=lambda: None,
    )


def _timeseries_response(data):
    return MagicMock(
        status_code=200,
        json=lambda: {"data": data},
        raise_for_status=lambda: None,
    )


class TestCoinMetricsCollector:
    @patch("on_chain.collectors.requests.get")
    def test_collect_daily(self, mock_get):
        catalog = _catalog_response([
            ("btc", ["FlowInExNtv", "FlowOutExNtv", "AdrActCnt", "CapMVRVCur"]),
        ])
        timeseries = _timeseries_response([{
            "asset": "btc",
            "time": "2026-03-18T00:00:00.000000000Z",
            "FlowInExNtv": "500.0",
            "FlowOutExNtv": "300.0",
            "AdrActCnt": "900000",
            "CapMVRVCur": "2.5",
        }])
        mock_get.side_effect = [catalog, timeseries]

        c = CoinMetricsCollector()
        rows = c.collect(["BTC"])
        assert len(rows) == 1
        assert rows[0]["asset"] == "BTC"
        assert rows[0]["mvrv"] == 2.5
        assert abs(rows[0]["nupl_computed"] - 0.6) < 0.01

    @patch("on_chain.collectors.requests.get")
    def test_missing_asset_returns_empty(self, mock_get):
        catalog = _catalog_response([])  # no assets in catalog
        mock_get.side_effect = [catalog]

        c = CoinMetricsCollector()
        rows = c.collect(["SOMI"])
        assert rows == []

    @patch("on_chain.collectors.requests.get")
    def test_partial_metrics_still_collected(self, mock_get):
        """Assets without flow metrics but with MVRV/AdrActCnt should still be collected."""
        catalog = _catalog_response([
            ("ada", ["AdrActCnt", "CapMVRVCur"]),  # no flows
        ])
        timeseries = _timeseries_response([{
            "asset": "ada",
            "time": "2026-03-18T00:00:00.000000000Z",
            "AdrActCnt": "500000",
            "CapMVRVCur": "1.8",
        }])
        mock_get.side_effect = [catalog, timeseries]

        c = CoinMetricsCollector()
        rows = c.collect(["ADA"])
        assert len(rows) == 1
        assert rows[0]["exchange_inflow_native"] == 0  # no flow data
        assert rows[0]["active_addresses"] == 500000
        assert rows[0]["mvrv"] == 1.8


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
