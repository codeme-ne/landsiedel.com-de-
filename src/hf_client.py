"""Hugging Face API Client with retry logic and error handling.

This module provides a resilient HTTP client for the Hugging Face Inference API.
Uses httpx for better timeout/connection handling and tenacity for retries.
"""
import logging
import os
from typing import Optional

import httpx
from tenacity import (
    RetryError,
    Retrying,
    before_sleep_log,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
    wait_random
)

logger = logging.getLogger(__name__)

# Suppress httpx debug logs to prevent token leakage
logging.getLogger('httpx').setLevel(logging.ERROR)


def _redact_token(token: str) -> str:
    """Redact API token for safe logging.

    Args:
        token: API token to redact

    Returns:
        Redacted token string
    """
    if not token:
        return "[EMPTY]"
    if len(token) <= 8:
        return "****"
    return f"{token[:4]}...{token[-4:]}"


# Custom exceptions for better error handling
class HfApiError(Exception):
    """Base exception for HF API errors"""
    pass


class AuthenticationError(HfApiError):
    """Raised when API token is invalid or missing"""
    pass


class RateLimitError(HfApiError):
    """Raised when rate limit is exceeded"""
    pass


class ModelError(HfApiError):
    """Raised when model is loading or unavailable"""
    pass


class HfClient:
    """Hugging Face API client with retry logic.

    Features:
    - Exponential backoff with jitter
    - Connection pooling via httpx
    - Typed exceptions for different error types
    - Configurable timeouts and retries
    """

    def __init__(
        self,
        api_token: Optional[str] = None,
        timeout: float = 30.0,
        max_retries: int = 3
    ):
        """Initialize HF client.

        Args:
            api_token: HF API token (defaults to HF_API_TOKEN env var)
            timeout: Request timeout in seconds
            max_retries: Maximum number of retry attempts
        """
        self.api_token = api_token or os.getenv('HF_API_TOKEN')
        if not self.api_token:
            raise AuthenticationError(
                "HF_API_TOKEN not set. Get one at: "
                "https://huggingface.co/settings/tokens"
            )

        self.timeout = timeout
        self.max_retries = max(1, max_retries)

        # Create httpx client with connection pooling
        self.client = httpx.Client(
            headers={"Authorization": f"Bearer {self.api_token}"},
            timeout=httpx.Timeout(timeout)
        )

        # Configure retry strategy with exponential backoff and jitter
        self._retry = Retrying(
            reraise=True,
            stop=stop_after_attempt(self.max_retries),
            wait=wait_exponential(multiplier=1, min=1, max=10) + wait_random(0, 1),
            retry=retry_if_exception_type((ModelError, httpx.TimeoutException, httpx.TransportError)),
            before_sleep=before_sleep_log(logger, logging.WARNING)
        )

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def close(self):
        """Close the HTTP client and release connections"""
        self.client.close()

    def _handle_response(self, response: httpx.Response) -> dict:
        """Parse and validate API response.

        Args:
            response: httpx Response object

        Returns:
            Parsed JSON response

        Raises:
            AuthenticationError: Invalid token
            RateLimitError: Rate limit exceeded
            ModelError: Model loading or unavailable
            HfApiError: Other API errors
        """
        # Handle specific HTTP status codes
        if response.status_code == 401:
            raise AuthenticationError("Invalid HF API token")

        if response.status_code == 429:
            raise RateLimitError("Rate limit exceeded. Try again later.")

        if response.status_code == 503:
            # Model loading - should retry
            raise ModelError("Model is loading, retrying...")

        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as e:
            raise HfApiError(f"API request failed: {e}")

        try:
            return response.json()
        except Exception as e:
            raise HfApiError(f"Failed to parse response: {e}")

    def translate_texts(
        self,
        texts: list[str],
        src: str,
        dst: str
    ) -> list[str]:
        """Translate multiple texts using MarianMT models.

        Args:
            texts: List of texts to translate
            src: Source language code (e.g., "de")
            dst: Destination language code (e.g., "en")

        Returns:
            List of translations in same order as input

        Raises:
            HfApiError: On API errors
            AuthenticationError: Invalid token
            RateLimitError: Rate limit exceeded
        """
        if not texts:
            return []

        def _call() -> list[str]:
            return self._translate_once(texts, src, dst)

        try:
            try:
                return self._retry(_call)
            except TypeError:
                if hasattr(self._retry, "call"):
                    return self._retry.call(_call)
                raise
        except RetryError as exc:  # pragma: no cover - defensive
            last_exc = exc.last_attempt.exception()
            if last_exc:
                raise last_exc
            raise

    def _translate_once(
        self,
        texts: list[str],
        src: str,
        dst: str
    ) -> list[str]:
        """Perform a single translation request."""
        from src.config import get_model_id

        model_id = get_model_id(src, dst)
        api_url = f"https://api-inference.huggingface.co/models/{model_id}"
        payload = {
            "inputs": texts,
            "options": {"wait_for_model": True}
        }

        try:
            response = self.client.post(api_url, json=payload)
        except httpx.TimeoutException as exc:
            logger.error("Request timeout after %.1fs", self.timeout)
            raise
        except httpx.TransportError as exc:
            logger.error("Network error during translation: %s", exc)
            raise
        result = self._handle_response(response)

        # Parse MarianMT response format
        translations: list[str] = []
        if isinstance(result, list):
            for item in result:
                translation = self._extract_translation(item)
                if translation is None:
                    fallback_index = len(translations)
                    fallback = texts[fallback_index] if fallback_index < len(texts) else ""
                    translations.append(fallback)
                else:
                    translations.append(translation)
        else:
            raise HfApiError(f"Unexpected response format: {type(result)}")

        if len(translations) != len(texts):
            logger.warning(
                "Translation count mismatch: expected %d, got %d",
                len(texts),
                len(translations)
            )
            while len(translations) < len(texts):
                translations.append(texts[len(translations)])

        return translations[:len(texts)]

    def _extract_translation(self, item) -> Optional[str]:
        """Extract translation text from API payload item."""
        if isinstance(item, dict):
            if 'translation_text' in item:
                return item['translation_text']
            if 'generated_text' in item:
                return item['generated_text']
        if isinstance(item, list) and item:
            # Some HF endpoints return nested list results per input
            return self._extract_translation(item[0])
        return None

    def health_check(self, src: str = "de", dst: str = "en") -> bool:
        """Verify API token and model availability.

        Args:
            src: Source language code to test
            dst: Destination language code to test

        Returns:
            True if API is accessible, False otherwise
        """
        try:
            # Make a minimal request to check connectivity
            from src.config import get_model_id
            model_id = get_model_id(src, dst)
            api_url = f"https://api-inference.huggingface.co/models/{model_id}"

            payload = {"inputs": "Test"}
            response = self.client.post(api_url, json=payload, timeout=10.0)
            self._handle_response(response)
            return True

        except AuthenticationError:
            logger.error("Authentication failed - invalid token")
            return False
        except (HfApiError, httpx.HTTPError) as e:
            logger.warning("Health check failed: %s", e)
            return False
