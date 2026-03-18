"""
Universal LLM client with OpenRouter primary and OpenAI fallback.

Supports two model paths:
  - Standard (batch): OPENROUTER_MODEL — used for bulk article processing
  - Fast (real-time):  OPENROUTER_MODEL_FAST — used for catalyst classification

Provider hierarchy:
  1. OpenRouter (OPENROUTER_API_KEY + OPENROUTER_MODEL / OPENROUTER_MODEL_FAST)
  2. OpenAI fallback (OPENAI_API_KEY + OPENAI_MODEL, default gpt-5.4-nano)

Both providers use the OpenAI SDK since OpenRouter exposes an OpenAI-compatible API.
"""

import logging
import os
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from openai import OpenAI

# ---------------------------------------------------------------------------
# Project root & environment
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Environment helpers
# ---------------------------------------------------------------------------

OPENROUTER_API_KEY: Optional[str] = os.getenv("OPENROUTER_API_KEY")
OPENROUTER_MODEL: Optional[str] = os.getenv("OPENROUTER_MODEL")
OPENROUTER_MODEL_FAST: Optional[str] = os.getenv("OPENROUTER_MODEL_FAST")

OPENAI_API_KEY: Optional[str] = os.getenv("OPENAI_API_KEY")
OPENAI_MODEL: str = os.getenv("OPENAI_MODEL", "gpt-5.4-nano")

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------


def get_llm_label() -> str:
    """Return a human-readable 'provider/model' string for the active config.

    Reflects the standard (batch) model, not the fast model.
    """
    if OPENROUTER_API_KEY and OPENROUTER_MODEL:
        return f"openrouter/{OPENROUTER_MODEL}"
    if OPENAI_API_KEY:
        return f"openai/{OPENAI_MODEL}"
    return "none/unconfigured"


def get_llm_client() -> tuple[OpenAI, str, str]:
    """Return the standard (batch) LLM client.

    Returns:
        (client, model_name, provider) where provider is
        ``"openrouter"`` or ``"openai"``.

    Raises:
        RuntimeError: If no API key is configured for any provider.
    """
    if OPENROUTER_API_KEY and OPENROUTER_MODEL:
        client = OpenAI(
            base_url=OPENROUTER_BASE_URL,
            api_key=OPENROUTER_API_KEY,
        )
        return client, OPENROUTER_MODEL, "openrouter"

    if OPENAI_API_KEY:
        client = OpenAI(api_key=OPENAI_API_KEY)
        return client, OPENAI_MODEL, "openai"

    raise RuntimeError(
        "No LLM provider configured. "
        "Set OPENROUTER_API_KEY + OPENROUTER_MODEL or OPENAI_API_KEY in .env"
    )


def get_llm_client_fast() -> tuple[OpenAI, str, str]:
    """Return the fast-path LLM client for real-time catalyst classification.

    Uses ``OPENROUTER_MODEL_FAST`` when available, otherwise falls back to
    the standard client returned by :func:`get_llm_client`.

    Returns:
        (client, model_name, provider)

    Raises:
        RuntimeError: If no API key is configured for any provider.
    """
    if OPENROUTER_API_KEY and OPENROUTER_MODEL_FAST:
        client = OpenAI(
            base_url=OPENROUTER_BASE_URL,
            api_key=OPENROUTER_API_KEY,
        )
        return client, OPENROUTER_MODEL_FAST, "openrouter"

    # Fall back to standard client (which itself falls back to OpenAI)
    return get_llm_client()


# ---------------------------------------------------------------------------
# Internal fallback
# ---------------------------------------------------------------------------


def _get_fallback_client() -> Optional[tuple[OpenAI, str, str]]:
    """Return the OpenAI fallback client, or ``None`` if unconfigured.

    This is used internally when the primary OpenRouter call fails.
    """
    if not OPENAI_API_KEY:
        return None
    client = OpenAI(api_key=OPENAI_API_KEY)
    return client, OPENAI_MODEL, "openai"


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def call_llm(
    system_prompt: str,
    user_prompt: str,
    temperature: float = 0.3,
    max_completion_tokens: int = 4000,
    fast: bool = False,
) -> tuple[str, dict, str]:
    """Send a prompt to the configured LLM and return the response.

    On the primary provider the call is retried once.  If both attempts fail
    and a fallback provider is available, it is tried once.

    Args:
        system_prompt: The system-role message content.
        user_prompt: The user-role message content.
        temperature: Sampling temperature (0.0 – 2.0).
        max_completion_tokens: Maximum tokens in the completion.
        fast: When ``True``, use the fast-path model
              (``OPENROUTER_MODEL_FAST``) instead of the batch model.

    Returns:
        A tuple of ``(content, usage_dict, llm_used_label)`` where:

        - *content* is the assistant's response text.
        - *usage_dict* is a dict with ``prompt_tokens``,
          ``completion_tokens``, and ``total_tokens``.
        - *llm_used_label* is a ``"provider/model"`` string identifying
          which model actually served the request.

    Raises:
        RuntimeError: If all providers fail.
    """
    primary_client, primary_model, primary_provider = (
        get_llm_client_fast() if fast else get_llm_client()
    )

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]

    # -- Primary: try up to 2 times (initial + 1 retry) -------------------
    last_error: Optional[Exception] = None
    for attempt in range(2):
        try:
            response = primary_client.chat.completions.create(
                model=primary_model,
                messages=messages,
                temperature=temperature,
                max_completion_tokens=max_completion_tokens,
            )
            usage = response.usage
            usage_dict = {
                "prompt_tokens": usage.prompt_tokens if usage else 0,
                "completion_tokens": usage.completion_tokens if usage else 0,
                "total_tokens": usage.total_tokens if usage else 0,
            }
            label = f"{primary_provider}/{primary_model}"
            content = response.choices[0].message.content or ""
            return content, usage_dict, label

        except Exception as exc:
            last_error = exc
            if attempt == 0:
                logger.warning(
                    "Primary LLM call failed (attempt %d), retrying: %s",
                    attempt + 1,
                    exc,
                )

    logger.warning(
        "Primary LLM exhausted retries (%s/%s). Attempting fallback.",
        primary_provider,
        primary_model,
    )

    # -- Fallback: OpenAI (single attempt) ---------------------------------
    fallback = _get_fallback_client()
    if fallback is None:
        raise RuntimeError(
            f"Primary LLM failed after retries and no fallback configured. "
            f"Last error: {last_error}"
        )

    fb_client, fb_model, fb_provider = fallback
    try:
        response = fb_client.chat.completions.create(
            model=fb_model,
            messages=messages,
            temperature=temperature,
            max_completion_tokens=max_completion_tokens,
        )
        usage = response.usage
        usage_dict = {
            "prompt_tokens": usage.prompt_tokens if usage else 0,
            "completion_tokens": usage.completion_tokens if usage else 0,
            "total_tokens": usage.total_tokens if usage else 0,
        }
        label = f"{fb_provider}/{fb_model}"
        content = response.choices[0].message.content or ""
        logger.info("Fallback LLM succeeded: %s", label)
        return content, usage_dict, label

    except Exception as fb_exc:
        raise RuntimeError(
            f"All LLM providers failed. "
            f"Primary ({primary_provider}/{primary_model}): {last_error}  "
            f"Fallback ({fb_provider}/{fb_model}): {fb_exc}"
        ) from fb_exc
