"""HTTP fetcher with retry logic and validation"""
import time
import logging
import requests
from requests.exceptions import Timeout, ConnectionError as ReqConnError, HTTPError

logger = logging.getLogger(__name__)


class FetchError(Exception):
    """Raised when fetch fails after retries"""
    pass


def fetch(url: str, timeout: int = 10, retries: int = 3,
          user_agent: str = "landsiedel-translation-bot/1.0") -> tuple[str, dict]:
    """
    Fetch URL with retries and validation.

    Returns (html, meta) where meta contains:
    - final_url: final URL after redirects
    - encoding: detected encoding
    - content_type: Content-Type header
    - status: HTTP status code

    Raises FetchError for non-HTML, 4xx/5xx after retries, or timeouts.
    """
    headers = {'User-Agent': user_agent}
    last_error = None

    for attempt in range(retries):
        try:
            logger.info(f"Fetching {url} (attempt {attempt + 1}/{retries})")

            resp = requests.get(url, headers=headers, timeout=timeout)
            resp.raise_for_status()

            # Validate content type
            content_type = resp.headers.get('content-type', '')
            if not content_type.lower().startswith('text/html'):
                raise FetchError(
                    f"Expected HTML but got {content_type}"
                )

            # Determine encoding
            encoding = resp.encoding or resp.apparent_encoding

            meta = {
                'final_url': resp.url,
                'encoding': encoding,
                'content_type': content_type,
                'status': resp.status_code,
            }

            return resp.text, meta

        except HTTPError as e:
            # Don't retry 4xx errors
            if e.response and 400 <= e.response.status_code < 500:
                raise FetchError(
                    f"HTTP {e.response.status_code}: {e}"
                ) from e
            last_error = e
            logger.warning(f"HTTP error on attempt {attempt + 1}: {e}")

        except (Timeout, ReqConnError) as e:
            last_error = e
            logger.warning(
                f"Network error on attempt {attempt + 1}: {e}"
            )

        # Exponential backoff: 0.5s, 1s, 2s
        if attempt < retries - 1:
            delay = 0.5 * (2 ** attempt)
            time.sleep(delay)

    raise FetchError(
        f"Failed after {retries} retries: {last_error}"
    ) from last_error
