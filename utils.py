"""Shared utilities."""

import time
import logging

logger = logging.getLogger(__name__)


def retry_with_backoff(func, max_retries=3, delays=(10, 30, 60), retryable_check=None):
    """
    Execute func with retry and backoff on transient errors.

    Args:
        func: Callable to execute (no arguments).
        max_retries: Maximum number of retries after initial attempt.
        delays: Tuple of sleep durations in seconds for each retry.
        retryable_check: Optional callable(exception) -> bool.
                         If provided, only retry when it returns True.
                         If not provided, all exceptions are retried.

    Returns:
        Result of func() on success.

    Raises:
        The last exception if all attempts fail or if retryable_check returns False.
    """
    for attempt in range(max_retries + 1):
        try:
            return func()
        except Exception as e:
            if retryable_check and not retryable_check(e):
                raise

            if attempt < max_retries:
                delay = delays[min(attempt, len(delays) - 1)]
                logger.warning(f"Attempt {attempt + 1}/{max_retries + 1} failed: {e}. Retrying in {delay}s...")
                time.sleep(delay)
            else:
                raise
