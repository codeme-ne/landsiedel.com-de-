"""Tests for fetcher module"""
import pytest
from unittest.mock import Mock, patch
import httpx
from src.fetcher import fetch, FetchError


def test_fetch_success_html():
    """Successfully fetch HTML content with metadata"""
    mock_response = Mock()
    mock_response.text = "<html><body>Test</body></html>"
    mock_response.headers = httpx.Headers({
        'content-type': 'text/html; charset=utf-8',
    })
    mock_response.encoding = 'utf-8'
    mock_response.status_code = 200
    mock_response.url = httpx.URL('https://example.com/page')

    mock_client = Mock()
    mock_client.get.return_value = mock_response

    with patch('src.fetcher._get_client', return_value=mock_client):
        html, meta = fetch('https://example.com/page')

    assert html == "<html><body>Test</body></html>"
    assert meta['final_url'] == 'https://example.com/page'
    assert meta['encoding'] == 'utf-8'
    assert meta['content_type'] == 'text/html; charset=utf-8'
    assert meta['status'] == 200


def test_404_raises_fetcherror():
    """HTTP 404 raises FetchError after retries"""
    mock_response = Mock()
    mock_response.status_code = 404

    http_error = httpx.HTTPStatusError(
        "404 Not Found",
        request=Mock(),
        response=mock_response
    )

    mock_client = Mock()
    mock_client.get.return_value = mock_response
    mock_response.raise_for_status.side_effect = http_error

    with patch('src.fetcher._get_client', return_value=mock_client):
        with pytest.raises(FetchError, match="404"):
            fetch('https://example.com/missing')


def test_timeout_and_retries():
    """Timeout causes retries then raises FetchError"""
    mock_client = Mock()
    mock_client.get.side_effect = httpx.TimeoutException("Connection timeout")

    with patch('src.fetcher._get_client', return_value=mock_client):
        with pytest.raises(FetchError, match="timeout|retries"):
            fetch('https://example.com/slow', retries=2)


def test_rejects_non_html():
    """Non-HTML content-type raises FetchError"""
    mock_response = Mock()
    mock_response.headers = httpx.Headers({'content-type': 'application/pdf'})
    mock_response.status_code = 200

    mock_client = Mock()
    mock_client.get.return_value = mock_response

    with patch('src.fetcher._get_client', return_value=mock_client):
        with pytest.raises(FetchError, match="HTML"):
            fetch('https://example.com/doc.pdf')


def test_encoding_fallback():
    """Falls back to utf-8 when encoding missing"""
    mock_response = Mock()
    mock_response.text = "<html>Ümlauts test</html>"
    mock_response.headers = httpx.Headers({'content-type': 'text/html'})
    mock_response.encoding = None
    mock_response.status_code = 200
    mock_response.url = httpx.URL('https://example.com/page')

    mock_client = Mock()
    mock_client.get.return_value = mock_response

    with patch('src.fetcher._get_client', return_value=mock_client):
        html, meta = fetch('https://example.com/page')

    assert meta['encoding'] == 'utf-8'
