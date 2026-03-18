# tests/test_onchain_models.py
import pytest
from datetime import datetime, date
from on_chain.models import ExchangeFlow, WhaleTransfer, OnChainDaily, OnChainSignal


class TestExchangeFlow:
    def test_netflow_computed(self):
        ef = ExchangeFlow(asset="BTC", date=date(2026, 3, 18),
                          inflow=500.0, outflow=300.0)
        assert ef.netflow == 200.0


class TestWhaleTransfer:
    def test_valid(self):
        wt = WhaleTransfer(
            tx_hash="0xabc", asset="ETH", timestamp=datetime.utcnow(),
            from_address="0x1", to_address="0x2", value_usd=2000000,
            direction="to_exchange", exchange_label="binance",
        )
        assert wt.direction == "to_exchange"


class TestOnChainDaily:
    def test_nupl_from_mvrv(self):
        ocd = OnChainDaily(asset="BTC", date=date(2026, 3, 18),
                           exchange_inflow_native=500, exchange_outflow_native=300,
                           exchange_netflow_native=200, mvrv=2.5,
                           nupl_computed=0.6, active_addresses=900000)
        # NUPL = 1 - 1/MVRV = 1 - 1/2.5 = 0.6
        assert abs(ocd.nupl_computed - (1 - 1 / ocd.mvrv)) < 0.01


class TestOnChainSignal:
    def test_score_range(self):
        s = OnChainSignal(asset="BTC", exchange_flow_score=0.3,
                          nupl_score=-0.2, active_addr_score=0.5,
                          whale_score=0.0, combined_score=0.2, confidence=0.8)
        assert -1.0 <= s.combined_score <= 1.0

    def test_from_sub_scores_with_renormalization(self):
        """When whale data is missing (score=None), renormalize weights."""
        s = OnChainSignal.from_sub_scores(
            asset="BTC",
            exchange_flow_score=0.6, nupl_score=-0.4,
            active_addr_score=0.2, whale_score=None,
            weights={"exchange_flow": 0.3, "nupl": 0.25,
                     "active_addresses": 0.15, "whale_activity": 0.3},
            confidence=0.9,
        )
        # whale excluded, weights renormalized: 0.3+0.25+0.15=0.7
        expected = (0.6 * 0.3 + (-0.4) * 0.25 + 0.2 * 0.15) / 0.7
        assert abs(s.combined_score - expected) < 1e-6
