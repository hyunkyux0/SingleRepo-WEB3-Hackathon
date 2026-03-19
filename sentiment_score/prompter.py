"""Sentiment scoring prompts and LLM calls.

Provides two scoring approaches:
- ``score_article_batch()`` — per-article scoring (deprecated, kept for backward compat)
- ``score_sector()`` — per-sector evidence-based scoring (v2, preferred)
"""

from __future__ import annotations

import json
import logging
import re

from utils.llm_client import call_llm

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# System prompt — batch path step 2 (scoring)
# ---------------------------------------------------------------------------

BATCH_SCORE_SYSTEM = """You are a crypto sentiment scorer. Given a news article and its classified sector, score the sentiment impact.

Rules:
- Score from -1.0 (extremely bearish) to +1.0 (extremely bullish)
- Consider: Is this news likely to move token prices in this sector up or down over the next 1-7 days?
- magnitude reflects expected price move size: low (<2%), medium (2-8%), high (>8%)
- confidence reflects how certain you are in the sentiment assessment

Output JSON only:
{
  "sentiment": <float -1.0 to 1.0>,
  "magnitude": "<low|medium|high>",
  "confidence": <float 0 to 1>,
  "reasoning": "<one sentence>"
}"""

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _strip_code_fences(text: str) -> str:
    """Remove markdown code fences from LLM output.

    Args:
        text: Raw LLM response text.

    Returns:
        Text with code fences stripped.
    """
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*\n?", "", text)
    text = re.sub(r"\n?```\s*$", "", text)
    return text.strip()


def _default_score() -> dict:
    """Return a safe default score when LLM parsing fails.

    Returns:
        A dict with neutral sentiment, low magnitude, zero confidence,
        and an explanatory reasoning string.
    """
    return {
        "sentiment": 0.0,
        "magnitude": "low",
        "confidence": 0.0,
        "reasoning": "Failed to parse LLM response; defaulted to neutral.",
    }


# ---------------------------------------------------------------------------
# Prompt builder
# ---------------------------------------------------------------------------


def build_batch_score_prompt(
    article_headline: str, article_snippet: str, sector: str
) -> str:
    """Format an article for batch sentiment scoring.

    Args:
        article_headline: The article headline.
        article_snippet: A short text snippet from the article body.
        sector: The sector the article was classified into.

    Returns:
        A formatted user-prompt string for the scoring LLM call.
    """
    parts = [
        f"Sector: {sector}",
        f"Headline: {article_headline}",
    ]
    if article_snippet:
        parts.append(f"Snippet: {article_snippet[:500]}")
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Scoring function
# ---------------------------------------------------------------------------


def score_article_batch(
    article_headline: str, article_snippet: str, sector: str
) -> dict:
    """Score an article's sentiment using the batch LLM model.

    Calls the LLM with ``fast=False`` and parses the returned JSON.
    On JSON parse failure, retries once before returning a default
    neutral score.  Sentiment is clamped to ``[-1, 1]``.

    Args:
        article_headline: The article headline.
        article_snippet: A short text snippet from the article body.
        sector: The sector the article was classified into.

    Returns:
        A dict with keys ``sentiment`` (float), ``magnitude`` (str),
        ``confidence`` (float), and ``reasoning`` (str).
    """
    user_prompt = build_batch_score_prompt(article_headline, article_snippet, sector)

    for attempt in range(2):
        try:
            content, usage, llm_label = call_llm(
                system_prompt=BATCH_SCORE_SYSTEM,
                user_prompt=user_prompt,
                temperature=0.2,
                max_completion_tokens=300,
                fast=False,
            )

            cleaned = _strip_code_fences(content)
            data = json.loads(cleaned)

            # Clamp sentiment to [-1, 1]
            sentiment = float(data.get("sentiment", 0.0))
            sentiment = max(-1.0, min(1.0, sentiment))

            # Validate magnitude
            magnitude = str(data.get("magnitude", "low")).lower()
            if magnitude not in ("low", "medium", "high"):
                magnitude = "low"

            confidence = float(data.get("confidence", 0.0))
            confidence = max(0.0, min(1.0, confidence))

            reasoning = str(data.get("reasoning", ""))

            logger.info(
                "Batch score: sentiment=%.2f magnitude=%s confidence=%.2f (via %s)",
                sentiment,
                magnitude,
                confidence,
                llm_label,
            )

            return {
                "sentiment": sentiment,
                "magnitude": magnitude,
                "confidence": confidence,
                "reasoning": reasoning,
            }

        except json.JSONDecodeError:
            if attempt == 0:
                logger.warning(
                    "Batch score JSON parse failed (attempt %d), retrying",
                    attempt + 1,
                )
                continue
            logger.error("Batch score JSON parse failed after retry; using default")

        except Exception:
            logger.exception("Batch score failed (attempt %d)", attempt + 1)
            if attempt == 0:
                continue

    return _default_score()


# ---------------------------------------------------------------------------
# v2: Per-sector evidence-based scoring
# ---------------------------------------------------------------------------

SECTOR_SCORE_SYSTEM = """You are scoring the net sentiment for a crypto sector.
Your score will be used as ONE input to a quantitative trading system.
Score conservatively — only strong, clear signals should produce extreme values.

Scoring rules:
- Score from -1.0 (extremely bearish) to +1.0 (extremely bullish)
- Score reflects expected NET price impact on this sector over the next 1-7 days
- Consider how news interacts with current market state:
  * Bullish news + already overleveraged long (high funding) = weaker signal
  * Bearish news + market already down significantly = potential reversal
  * High article velocity on same topic = stronger signal
  * Multiple independent bullish/bearish stories = stronger than a single story
- magnitude: low (<2% expected move), medium (2-8%), high (>8%)
- Your reasoning MUST reference at least one piece of market context evidence

Output JSON only:
{
  "sentiment": <float -1.0 to 1.0>,
  "magnitude": "<low|medium|high>",
  "confidence": <float 0 to 1>,
  "key_driver": "<the single most important factor driving the score>",
  "reasoning": "<2-3 sentences explaining score, referencing market context>"
}"""


def build_sector_score_prompt(summary: dict, evidence: dict) -> str:
    """Build the user prompt for sector-level scoring.

    Args:
        summary: Output of ``build_sector_summary()``.
        evidence: Output of ``gather_evidence()``.

    Returns:
        Formatted user-prompt string.
    """
    parts = [f"Sector: {summary['sector']}", "", "=== Market Context ==="]

    # Token prices
    prices = evidence.get("token_prices", [])
    if prices:
        price_strs = [
            f"{p['ticker']} ${p['price']:.2f} ({p['change_24h_pct']:+.1f}% 24h)"
            for p in prices
        ]
        parts.append(f"Sector tokens: {', '.join(price_strs)}")

    parts.append(
        f"Article velocity: {summary['article_count']} articles "
        f"in lookback window ({summary['velocity']})"
    )
    parts.append(f"Previous sentiment score: {evidence.get('previous_sentiment', 0.0)}")

    # Optional signals
    if evidence.get("funding_rate") is not None:
        fr = evidence["funding_rate"]
        interp = "longs paying shorts" if fr > 0 else "shorts paying longs"
        parts.append(f"Funding rate: {fr:.4f}% ({interp})")
    if evidence.get("nupl") is not None:
        parts.append(f"NUPL: {evidence['nupl']:.3f}")
    if evidence.get("exchange_net_flow") is not None:
        parts.append(f"Exchange net flow: {evidence['exchange_net_flow']}")

    # Headlines
    headlines = summary.get("top_headlines", [])
    if headlines:
        parts.append(
            f"\n=== News Events ({summary['article_count']} articles) ==="
        )
        for i, hl in enumerate(headlines, 1):
            catalyst_tag = " [CATALYST]" if hl.get("is_catalyst") else ""
            parts.append(
                f"{i}. [{hl['source']}, {hl['age_hours']:.0f}h ago]"
                f"{catalyst_tag} {hl['headline']}"
            )
            if hl.get("snippet"):
                parts.append(f"   -> {hl['snippet'][:200]}")

    parts.append(
        f"\nScore the net sentiment impact on the {summary['sector']} sector."
    )
    return "\n".join(parts)


def score_sector(summary: dict, evidence: dict) -> dict:
    """Score a sector's sentiment using ONE LLM call with evidence.

    Skips the LLM call entirely for sectors with zero articles,
    returning a neutral default.

    Args:
        summary: Output of ``build_sector_summary()``.
        evidence: Output of ``gather_evidence()``.

    Returns:
        Dict with sentiment, magnitude, confidence, key_driver, reasoning.
    """
    if summary.get("article_count", 0) == 0:
        return {
            "sentiment": 0.0,
            "magnitude": "low",
            "confidence": 0.0,
            "key_driver": "",
            "reasoning": "No articles in window.",
        }

    user_prompt = build_sector_score_prompt(summary, evidence)

    for attempt in range(2):
        try:
            content, usage, llm_label = call_llm(
                system_prompt=SECTOR_SCORE_SYSTEM,
                user_prompt=user_prompt,
                temperature=0.2,
                max_completion_tokens=500,
                fast=False,
            )

            cleaned = _strip_code_fences(content)
            data = json.loads(cleaned)

            sentiment = max(-1.0, min(1.0, float(data.get("sentiment", 0.0))))
            magnitude = str(data.get("magnitude", "low")).lower()
            if magnitude not in ("low", "medium", "high"):
                magnitude = "low"
            confidence = max(0.0, min(1.0, float(data.get("confidence", 0.0))))

            logger.info(
                "score_sector [%s]: sentiment=%.2f magnitude=%s confidence=%.2f "
                "key_driver=%s (via %s)",
                summary["sector"], sentiment, magnitude, confidence,
                data.get("key_driver", "")[:40], llm_label,
            )

            return {
                "sentiment": sentiment,
                "magnitude": magnitude,
                "confidence": confidence,
                "key_driver": str(data.get("key_driver", "")),
                "reasoning": str(data.get("reasoning", "")),
            }

        except json.JSONDecodeError:
            if attempt == 0:
                logger.warning("score_sector JSON parse failed, retrying")
                continue
            logger.error("score_sector JSON parse failed after retry")
        except Exception:
            logger.exception("score_sector failed (attempt %d)", attempt + 1)
            if attempt == 0:
                continue

    return {
        "sentiment": 0.0,
        "magnitude": "low",
        "confidence": 0.0,
        "key_driver": "",
        "reasoning": "LLM scoring failed.",
    }
