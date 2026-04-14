"""Gemini-based meeting summary generation."""
import logging

from google import genai
from google.genai import types

import config
from transcription_client import UsageStats
from utils import retry_with_backoff

logger = logging.getLogger(__name__)


def _load_prompt() -> str:
    return config.SUMMARY_PROMPT_PATH.read_text(encoding="utf-8")


def generate_summary(transcript: str) -> tuple[str, UsageStats]:
    """
    Generate a meeting summary from a transcript using Gemini.

    Raises on failure. Returns (summary_text, usage_stats).
    """
    usage = UsageStats()

    if not config.GEMINI_API_KEY:
        raise RuntimeError("Summary skipped: GEMINI_API_KEY not configured")

    if not config.SUMMARY_PROMPT_PATH.exists():
        raise FileNotFoundError(f"Summary prompt not found: {config.SUMMARY_PROMPT_PATH}")

    prompt = _load_prompt()
    client = genai.Client(api_key=config.GEMINI_API_KEY)

    logger.info(f"Generating summary via {config.GEMINI_MODEL}")

    def _generate():
        return client.models.generate_content(
            model=config.GEMINI_MODEL,
            contents=[prompt + "\n\n---\n\n" + transcript],
            config=types.GenerateContentConfig(
                max_output_tokens=16384,
                temperature=0.3,
            ),
        )

    def _is_retryable(e: Exception):
        error_str = str(e).lower()
        if "400" in error_str and "bad request" in error_str:
            return False
        return True

    response = retry_with_backoff(
        _generate, max_retries=3, delays=(15, 45, 90), retryable_check=_is_retryable
    )

    usage.add_response(response)

    if not response.text:
        finish_reason = None
        if response.candidates:
            finish_reason = response.candidates[0].finish_reason
        raise RuntimeError(f"Summary generation returned empty response (finish_reason={finish_reason})")

    summary = response.text.strip()
    logger.info(f"Summary generated: {len(summary)} chars ({usage.cost_string()})")
    return summary, usage
