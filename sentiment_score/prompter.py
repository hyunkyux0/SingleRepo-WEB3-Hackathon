"""Batch sentiment scoring prompts and LLM calls (batch path step 2).

After an article has been classified into a sector by the
``news_sentiment`` module, this module scores its sentiment impact
using the batch LLM model.
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
