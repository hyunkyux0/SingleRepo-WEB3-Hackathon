"""News ingestion, deduplication, keyword pre-filtering, and LLM-based sector classification."""

from news_sentiment.models import ArticleInput, ClassificationOutput

__all__ = ["ArticleInput", "ClassificationOutput"]
