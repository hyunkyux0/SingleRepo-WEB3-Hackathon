# tests/test_onchain_processors.py
import pytest
from on_chain.processors import (
    score_exchange_flow,
    score_nupl,
    score_active_addresses,
    score_whale_activity,
    generate_on_chain_signal,
)
from on_chain.models import OnChainSignal


class TestExchangeFlowScore:
    def test_net_inflow_negative(self):
        """Net inflow = selling pressure = negative score."""
        score = score_exchange_flow(netflow=200.0, avg_30d_netflow=0.0, std_30d=100.0)
        assert score < 0

    def test_net_outflow_positive(self):
        """Net outflow = accumulation = positive score."""
        score = score_exchange_flow(netflow=-200.0, avg_30d_netflow=0.0, std_30d=100.0)
        assert score > 0

    def test_clamped(self):
        assert -1.0 <= score_exchange_flow(10000, 0, 100) <= 1.0


class TestNUPLScore:
    def test_euphoria_negative(self):
        """NUPL > 0.75 = euphoria = negative score."""
        score = score_nupl(0.8)
        assert score < 0

    def test_capitulation_positive(self):
        """NUPL < 0 = capitulation = positive score."""
        score = score_nupl(-0.1)
        assert score > 0

    def test_neutral(self):
        """NUPL around 0.4 = mid-cycle = near zero."""
        score = score_nupl(0.4)
        assert abs(score) < 0.5

    def test_clamped(self):
        assert -1.0 <= score_nupl(1.5) <= 1.0
        assert -1.0 <= score_nupl(-1.0) <= 1.0


class TestActiveAddresses:
    def test_growing_positive(self):
        score = score_active_addresses(growth_rate_30d=0.1)
        assert score > 0

    def test_declining_negative(self):
        score = score_active_addresses(growth_rate_30d=-0.1)
        assert score < 0


class TestWhaleActivity:
    def test_net_to_exchange_negative(self):
        """Net transfers to exchanges = sell pressure = negative."""
        score = score_whale_activity(
            to_exchange_usd=5000000, from_exchange_usd=1000000
        )
        assert score < 0

    def test_net_from_exchange_positive(self):
        """Net transfers from exchanges = accumulation = positive."""
        score = score_whale_activity(
            to_exchange_usd=1000000, from_exchange_usd=5000000
        )
        assert score > 0

    def test_no_transfers_neutral(self):
        score = score_whale_activity(to_exchange_usd=0, from_exchange_usd=0)
        assert score == 0.0


class TestGenerateOnChainSignal:
    def test_returns_signal_with_whale(self):
        signal = generate_on_chain_signal(
            asset="ETH", netflow=100.0, avg_30d_netflow=50.0, std_30d=80.0,
            nupl=0.5, active_addr_growth=0.05,
            whale_to_exchange_usd=2000000, whale_from_exchange_usd=1000000,
            config={
                "sub_weights": {"exchange_flow": 0.3, "nupl": 0.25,
                                "active_addresses": 0.15, "whale_activity": 0.3},
            },
        )
        assert isinstance(signal, OnChainSignal)
        assert signal.confidence > 0

    def test_returns_signal_without_whale(self):
        """Non-ETH assets: whale data absent, weights renormalized."""
        signal = generate_on_chain_signal(
            asset="BTC", netflow=100.0, avg_30d_netflow=50.0, std_30d=80.0,
            nupl=0.5, active_addr_growth=0.05,
            whale_to_exchange_usd=None, whale_from_exchange_usd=None,
            config={
                "sub_weights": {"exchange_flow": 0.3, "nupl": 0.25,
                                "active_addresses": 0.15, "whale_activity": 0.3},
            },
        )
        assert isinstance(signal, OnChainSignal)
        assert signal.whale_score == 0.0
