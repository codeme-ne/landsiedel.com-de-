"""HTTP fetcher with retry logic and validation"""
import time
import logging
import socket
import ipaddress
import atexit
from urllib.parse import urlparse
import httpx

logger = logging.getLogger(__name__)

# Module-level HTTP client for connection pooling
_client: httpx.Client | None = None


class FetchError(Exception):
    """Raised when fetch fails after retries"""
    pass


class SSRFError(FetchError):
    """Raised when URL fails SSRF validation"""
    pass


# Private IP ranges to block
PRIVATE_IP_RANGES = [
    ipaddress.ip_network('10.0.0.0/8'),
    ipaddress.ip_network('172.16.0.0/12'),
    ipaddress.ip_network('192.168.0.0/16'),
    ipaddress.ip_network('169.254.0.0/16'),  # Link-local
    ipaddress.ip_network('127.0.0.0/8'),     # Loopback
    ipaddress.ip_network('::1/128'),         # IPv6 loopback
    ipaddress.ip_network('fc00::/7'),        # IPv6 private
    ipaddress.ip_network('fe80::/10'),       # IPv6 link-local
]

# Cloud metadata endpoints
METADATA_IPS = ['169.254.169.254']


def validate_url(url: str) -> None:
    """
    Validate URL to prevent SSRF attacks.

    Blocks:
    - Non-HTTP(S) schemes
    - Localhost, 127.0.0.1, 0.0.0.0, ::1
    - Cloud metadata endpoint (169.254.169.254)
    - Private IP ranges (10.x, 172.16-31.x, 192.168.x)
    - Link-local addresses

    Raises SSRFError if URL is blocked.
    """
    parsed = urlparse(url)

    # Only allow HTTP and HTTPS
    if parsed.scheme not in ('http', 'https'):
        raise SSRFError(
            f"Invalid scheme '{parsed.scheme}': only http/https allowed"
        )

    hostname = parsed.hostname
    if not hostname:
        raise SSRFError("URL must contain a hostname")

    # Block localhost variants
    localhost_names = {'localhost', 'localhost.localdomain'}
    if hostname.lower() in localhost_names:
        raise SSRFError(f"Access to localhost is blocked")

    # Resolve hostname to IP and validate
    try:
        # Get all IP addresses for this hostname
        addr_info = socket.getaddrinfo(hostname, None)
        ips = {info[4][0] for info in addr_info}

        for ip_str in ips:
            # Parse as IP address
            ip = ipaddress.ip_address(ip_str)

            # Block loopback
            if ip.is_loopback:
                raise SSRFError(
                    f"Loopback address blocked: {ip_str}"
                )

            # Block link-local
            if ip.is_link_local:
                raise SSRFError(
                    f"Link-local address blocked: {ip_str}"
                )

            # Block cloud metadata endpoint
            if ip_str in METADATA_IPS:
                raise SSRFError(
                    f"Cloud metadata endpoint blocked: {ip_str}"
                )

            # Block private IP ranges
            for private_range in PRIVATE_IP_RANGES:
                if ip in private_range:
                    raise SSRFError(
                        f"Private IP address blocked: {ip_str} "
                        f"(in {private_range})"
                    )

    except socket.gaierror as e:
        raise SSRFError(f"Failed to resolve hostname: {e}") from e


def _get_client() -> httpx.Client:
    """
    Get or create the module-level HTTP client with connection pooling.

    Configured with:
    - Connection pooling (max 10 connections, 5 keepalive)
    - 10s default timeout
    - Automatic redirect following
    - Cleanup registered with atexit
    """
    global _client
    if _client is None:
        _client = httpx.Client(
            timeout=httpx.Timeout(10.0),
            limits=httpx.Limits(
                max_connections=10,
                max_keepalive_connections=5
            ),
            follow_redirects=True
        )
        atexit.register(_client.close)
    return _client


def fetch(url: str, timeout: int = 10, retries: int = 3,
          user_agent: str = "landsiedel-translation-bot/1.0") -> tuple[str, dict]:
    """
    Fetch URL with retries and validation using connection pooling.

    Returns (html, meta) where meta contains:
    - final_url: final URL after redirects
    - encoding: detected encoding
    - content_type: Content-Type header
    - status: HTTP status code

    Raises FetchError for non-HTML, 4xx/5xx after retries, or timeouts.
    """
    # Validate URL to prevent SSRF attacks
    validate_url(url)

    headers = {'User-Agent': user_agent}
    client = _get_client()
    last_error = None

    for attempt in range(retries):
        try:
            logger.info(f"Fetching {url} (attempt {attempt + 1}/{retries})")

            # Use client with connection pooling
            resp = client.get(
                url,
                headers=headers,
                timeout=httpx.Timeout(float(timeout))
            )
            resp.raise_for_status()

            # Validate content type
            content_type = resp.headers.get('content-type', '')
            if not content_type.lower().startswith('text/html'):
                raise FetchError(
                    f"Expected HTML but got {content_type}"
                )

            # Determine encoding (httpx handles this automatically)
            encoding = resp.encoding or 'utf-8'

            meta = {
                'final_url': str(resp.url),
                'encoding': encoding,
                'content_type': content_type,
                'status': resp.status_code,
            }

            return resp.text, meta

        except httpx.HTTPStatusError as e:
            # Don't retry 4xx errors
            if 400 <= e.response.status_code < 500:
                raise FetchError(
                    f"HTTP {e.response.status_code}: {e}"
                ) from e
            last_error = e
            logger.warning(f"HTTP error on attempt {attempt + 1}: {e}")

        except (httpx.TimeoutException, httpx.ConnectError,
                httpx.RemoteProtocolError) as e:
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
