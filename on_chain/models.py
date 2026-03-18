"""Pydantic models for on-chain data and signals."""
from datetime import datetime, date as date_type
from typing import Optional
from pydantic import BaseModel, Field, computed_field


class ExchangeFlow(BaseModel):
    asset: str
    date: date_type
    inflow: float
    outflow: float

    @computed_field
    @property
    def netflow(self) -> float:
        return self.inflow - self.outflow


class WhaleTransfer(BaseModel):
    tx_hash: str
    asset: str
    timestamp: datetime
    from_address: str
    to_address: str
    value_usd: float
    direction: str  # 'to_exchange', 'from_exchange', 'unknown'
    exchange_label: Optional[str] = None


class OnChainDaily(BaseModel):
    asset: str
    date: date_type
    exchange_inflow_native: float
    exchange_outflow_native: float
    exchange_netflow_native: float
    mvrv: float
    nupl_computed: float
    active_addresses: int


class OnChainSignal(BaseModel):
    asset: str
    exchange_flow_score: float = Field(ge=-1.0, le=1.0)
    nupl_score: float = Field(ge=-1.0, le=1.0)
    active_addr_score: float = Field(ge=-1.0, le=1.0)
    whale_score: float = Field(ge=-1.0, le=1.0)
    combined_score: float = Field(ge=-1.0, le=1.0)
    confidence: float = Field(ge=0.0, le=1.0)

    @classmethod
    def from_sub_scores(
        cls, asset: str, exchange_flow_score: float,
        nupl_score: float, active_addr_score: float,
        whale_score: Optional[float], weights: dict,
        confidence: float,
    ) -> "OnChainSignal":
        """Combine sub-scores. If whale_score is None, renormalize weights."""
        scores = {
            "exchange_flow": exchange_flow_score,
            "nupl": nupl_score,
            "active_addresses": active_addr_score,
        }
        effective_weights = {
            "exchange_flow": weights["exchange_flow"],
            "nupl": weights["nupl"],
            "active_addresses": weights["active_addresses"],
        }
        if whale_score is not None:
            scores["whale_activity"] = whale_score
            effective_weights["whale_activity"] = weights["whale_activity"]

        total_w = sum(effective_weights.values())
        combined = sum(
            scores[k] * effective_weights[k] for k in scores
        ) / total_w if total_w > 0 else 0.0
        combined = max(-1.0, min(1.0, combined))

        return cls(
            asset=asset,
            exchange_flow_score=exchange_flow_score,
            nupl_score=nupl_score,
            active_addr_score=active_addr_score,
            whale_score=whale_score if whale_score is not None else 0.0,
            combined_score=combined,
            confidence=confidence,
        )
