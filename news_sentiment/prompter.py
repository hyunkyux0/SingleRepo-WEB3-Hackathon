"""LLM prompts and classification functions for the news sentiment pipeline.

Contains system prompts for fast-path (single-shot) and batch-path
(classification-only) processing, prompt builders, and classification
functions that call the shared LLM client.
"""

from __future__ import annotations

import json
import logging
import re

from news_sentiment.models import ArticleInput, ClassificationOutput
from utils.llm_client import call_llm

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Valid sectors — used to validate LLM output
# ---------------------------------------------------------------------------

VALID_SECTORS: set[str] = {
    "l1_infra",
    "defi",
    "ai_compute",
    "meme",
    "store_of_value",
    "other",
}

# ---------------------------------------------------------------------------
# System prompts
# ---------------------------------------------------------------------------

FAST_CLASSIFY_SYSTEM = """You are a crypto news classifier. Given a headline and snippet, output JSON only.

Sectors: l1_infra, defi, ai_compute, meme, store_of_value, other

Rules:
- Classify into the single most affected sector
- If equity news maps to a crypto sector (e.g., NVIDIA -> ai_compute), set cross_market: true
- Score sentiment from the perspective of price impact over 1-7 days
- magnitude reflects expected price move size, not certainty

Output format:
{
  "primary_sector": "<primary sector affected>",
  "secondary_sector": "<if applicable, else null>",
  "sentiment": <float -1.0 to 1.0>,
  "magnitude": "<low|medium|high>",
  "confidence": <float 0 to 1>,
  "cross_market": <bool>,
  "reasoning": "<one sentence>"
}"""

BATCH_CLASSIFY_SYSTEM = """You are a crypto sector classifier. Given a news article, determine which crypto sector it most affects.

Sectors and descriptions:
- l1_infra: Layer 1 blockchains, infrastructure, scaling solutions
- defi: Decentralized finance protocols, lending, DEXes, yield
- ai_compute: AI tokens, compute networks, machine learning projects
- meme: Meme coins, community-driven tokens, social tokens
- store_of_value: Bitcoin-like stores of value, gold-pegged, privacy coins
- other: Tokens that don't fit above categories

Rules:
- Consider cross-market signals: equity news (e.g., NVIDIA, Google AI) that maps to crypto sectors
- If the article affects multiple sectors, pick the primary and note secondary
- confidence reflects how clearly the article maps to a single sector

Output JSON only:
{
  "primary_sector": "<sector>",
  "secondary_sector": "<sector or null>",
  "confidence": <float 0 to 1>,
  "cross_market": <bool>
}"""

# ---------------------------------------------------------------------------
# Prompt builders
# ---------------------------------------------------------------------------


def build_fast_classify_prompt(article: ArticleInput) -> str:
    """Format an article for the fast-path (single-shot) LLM classification.

    Includes headline, body snippet, source, and any pre-identified tickers
    to give the LLM maximum context in one call.

    Args:
        article: The article to classify.

    Returns:
        A formatted user-prompt string.
    """
    parts = [
        f"Headline: {article.headline}",
    ]
    if article.body_snippet:
        parts.append(f"Snippet: {article.body_snippet[:500]}")
    parts.append(f"Source: {article.source}")
    if article.mentioned_tickers:
        parts.append(f"Mentioned tickers: {', '.join(article.mentioned_tickers)}")
    if article.matched_sectors:
        parts.append(f"Pre-matched sectors: {', '.join(article.matched_sectors)}")

    return "\n".join(parts)


def build_batch_classify_prompt(article: ArticleInput) -> str:
    """Format an article for the batch-path (classification-only) LLM call.

    Similar to the fast-path prompt but focused on sector classification
    without requesting sentiment scoring.

    Args:
        article: The article to classify.

    Returns:
        A formatted user-prompt string.
    """
    parts = [
        f"Headline: {article.headline}",
    ]
    if article.body_snippet:
        parts.append(f"Snippet: {article.body_snippet[:500]}")
    parts.append(f"Source: {article.source}")
    if article.mentioned_tickers:
        parts.append(f"Mentioned tickers: {', '.join(article.mentioned_tickers)}")

    return "\n".join(parts)


# ---------------------------------------------------------------------------
# JSON parsing helpers
# ---------------------------------------------------------------------------


def _strip_code_fences(text: str) -> str:
    """Remove markdown code fences from LLM output.

    LLMs sometimes wrap JSON in ```json ... ``` blocks.

    Args:
        text: Raw LLM response text.

    Returns:
        Text with code fences stripped.
    """
    text = text.strip()
    # Remove ```json ... ``` or ``` ... ```
    text = re.sub(r"^```(?:json)?\s*\n?", "", text)
    text = re.sub(r"\n?```\s*$", "", text)
    return text.strip()


def _validate_sector(sector: str | None) -> str | None:
    """Validate a sector string against the known set.

    Args:
        sector: Sector string from LLM output.

    Returns:
        The sector if valid, ``"other"`` if invalid but non-empty,
        or ``None`` if the input was ``None`` or empty.
    """
    if sector is None or sector == "null":
        return None
    sector = sector.strip().lower()
    if not sector:
        return None
    if sector not in VALID_SECTORS:
        logger.warning("LLM returned unknown sector %r; mapping to 'other'", sector)
        return "other"
    return sector


def _default_classification() -> ClassificationOutput:
    """Return a safe default classification when LLM parsing fails.

    Returns:
        A ``ClassificationOutput`` with sector ``"other"`` and neutral
        sentiment.
    """
    return ClassificationOutput(
        primary_sector="other",
        secondary_sector=None,
        sentiment=0.0,
        magnitude="low",
        confidence=0.0,
        cross_market=False,
        reasoning="Failed to parse LLM response; defaulted to other.",
    )


# ---------------------------------------------------------------------------
# Classification functions
# ---------------------------------------------------------------------------


def classify_article_fast(article: ArticleInput) -> ClassificationOutput:
    """Classify an article using the fast-path LLM (single-shot).

    Calls the LLM with ``fast=True`` to get sector classification and
    sentiment scoring in a single request.  On JSON parse failure, retries
    once before returning a default ``"other"`` classification.

    Args:
        article: The article to classify.

    Returns:
        A :class:`ClassificationOutput` with all fields populated.
    """
    user_prompt = build_fast_classify_prompt(article)

    for attempt in range(2):
        try:
            content, usage, llm_label = call_llm(
                system_prompt=FAST_CLASSIFY_SYSTEM,
                user_prompt=user_prompt,
                temperature=0.2,
                max_completion_tokens=500,
                fast=True,
            )

            cleaned = _strip_code_fences(content)
            data = json.loads(cleaned)

            primary = _validate_sector(data.get("primary_sector")) or "other"
            secondary = _validate_sector(data.get("secondary_sector"))

            # Clamp sentiment to [-1, 1]
            sentiment = float(data.get("sentiment", 0.0))
            sentiment = max(-1.0, min(1.0, sentiment))

            # Validate magnitude
            magnitude = str(data.get("magnitude", "low")).lower()
            if magnitude not in ("low", "medium", "high"):
                magnitude = "low"

            confidence = float(data.get("confidence", 0.0))
            confidence = max(0.0, min(1.0, confidence))

            result = ClassificationOutput(
                primary_sector=primary,
                secondary_sector=secondary,
                sentiment=sentiment,
                magnitude=magnitude,
                confidence=confidence,
                cross_market=bool(data.get("cross_market", False)),
                reasoning=str(data.get("reasoning", "")),
            )

            logger.info(
                "Fast classify [%s]: sector=%s sentiment=%.2f magnitude=%s (via %s)",
                article.id,
                result.primary_sector,
                result.sentiment,
                result.magnitude,
                llm_label,
            )
            return result

        except json.JSONDecodeError:
            if attempt == 0:
                logger.warning(
                    "Fast classify JSON parse failed for article %s (attempt %d), retrying",
                    article.id,
                    attempt + 1,
                )
                continue
            logger.error(
                "Fast classify JSON parse failed for article %s after retry; using default",
                article.id,
            )
        except Exception:
            logger.exception(
                "Fast classify failed for article %s (attempt %d)",
                article.id,
                attempt + 1,
            )
            if attempt == 0:
                continue

    return _default_classification()


def classify_article_batch(article: ArticleInput) -> ClassificationOutput:
    """Classify an article using the batch-path LLM (classification only).

    Calls the LLM with ``fast=False`` for sector classification.  Sentiment
    and magnitude fields are left at defaults (``0.0`` / ``"low"``) since
    batch sentiment scoring happens in the ``sentiment_score`` module.

    On JSON parse failure, retries once before returning a default ``"other"``
    classification.

    Args:
        article: The article to classify.

    Returns:
        A :class:`ClassificationOutput` with sector fields populated and
        sentiment/magnitude at defaults.
    """
    user_prompt = build_batch_classify_prompt(article)

    for attempt in range(2):
        try:
            content, usage, llm_label = call_llm(
                system_prompt=BATCH_CLASSIFY_SYSTEM,
                user_prompt=user_prompt,
                temperature=0.2,
                max_completion_tokens=300,
                fast=False,
            )

            cleaned = _strip_code_fences(content)
            data = json.loads(cleaned)

            primary = _validate_sector(data.get("primary_sector")) or "other"
            secondary = _validate_sector(data.get("secondary_sector"))

            confidence = float(data.get("confidence", 0.0))
            confidence = max(0.0, min(1.0, confidence))

            result = ClassificationOutput(
                primary_sector=primary,
                secondary_sector=secondary,
                sentiment=0.0,  # scored separately in sentiment_score module
                magnitude="low",  # scored separately in sentiment_score module
                confidence=confidence,
                cross_market=bool(data.get("cross_market", False)),
                reasoning="",  # not produced by batch classification prompt
            )

            logger.info(
                "Batch classify [%s]: sector=%s confidence=%.2f (via %s)",
                article.id,
                result.primary_sector,
                result.confidence,
                llm_label,
            )
            return result

        except json.JSONDecodeError:
            if attempt == 0:
                logger.warning(
                    "Batch classify JSON parse failed for article %s (attempt %d), retrying",
                    article.id,
                    attempt + 1,
                )
                continue
            logger.error(
                "Batch classify JSON parse failed for article %s after retry; using default",
                article.id,
            )
        except Exception:
            logger.exception(
                "Batch classify failed for article %s (attempt %d)",
                article.id,
                attempt + 1,
            )
            if attempt == 0:
                continue

    return _default_classification()
