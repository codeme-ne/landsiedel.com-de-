"""Tests for fetcher module"""
import pytest
from unittest.mock import Mock, patch
from requests.exceptions import Timeout, HTTPError
from src.fetcher import fetch, FetchError


def test_fetch_success_html():
    """Successfully fetch HTML content with metadata"""
    mock_response = Mock()
    mock_response.text = "<html><body>Test</body></html>"
    mock_response.headers = {
        'content-type': 'text/html; charset=utf-8',
    }
    mock_response.encoding = 'utf-8'
    mock_response.status_code = 200
    mock_response.url = 'https://example.com/page'

    with patch('requests.get', return_value=mock_response):
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

    http_error = HTTPError("404 Not Found")
    http_error.response = mock_response
    mock_response.raise_for_status.side_effect = http_error

    with patch('requests.get', return_value=mock_response):
        with pytest.raises(FetchError, match="404"):
            fetch('https://example.com/missing')


def test_timeout_and_retries():
    """Timeout causes retries then raises FetchError"""
    with patch('requests.get', side_effect=Timeout("Connection timeout")):
        with pytest.raises(FetchError, match="timeout|retries"):
            fetch('https://example.com/slow', retries=2)


def test_rejects_non_html():
    """Non-HTML content-type raises FetchError"""
    mock_response = Mock()
    mock_response.headers = {'content-type': 'application/pdf'}
    mock_response.status_code = 200

    with patch('requests.get', return_value=mock_response):
        with pytest.raises(FetchError, match="HTML"):
            fetch('https://example.com/doc.pdf')


def test_encoding_fallback():
    """Falls back to apparent_encoding when encoding missing"""
    mock_response = Mock()
    mock_response.text = "<html>Ümlauts test</html>"
    mock_response.headers = {'content-type': 'text/html'}
    mock_response.encoding = None
    mock_response.apparent_encoding = 'utf-8'
    mock_response.status_code = 200
    mock_response.url = 'https://example.com/page'

    with patch('requests.get', return_value=mock_response):
        html, meta = fetch('https://example.com/page')

    assert meta['encoding'] == 'utf-8'
