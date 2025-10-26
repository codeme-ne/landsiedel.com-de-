"""Unit tests for the Hugging Face client wrapper."""

from types import SimpleNamespace

import httpx
import pytest

from src.hf_client import (
    AuthenticationError,
    HfApiError,
    HfClient,
    ModelError,
    RateLimitError,
)


class FakeResponse:
    """Lightweight stand-in for httpx.Response."""

    def __init__(self, status_code=200, json_data=None, raise_error=None, json_error=None):
        self.status_code = status_code
        self._json_data = json_data or []
        self._raise_error = raise_error
        self._json_error = json_error

    def raise_for_status(self):
        if self._raise_error:
            raise self._raise_error

    def json(self):
        if self._json_error:
            raise self._json_error
        return self._json_data


class StubClient:
    """Fake httpx.Client that returns a sequence of responses."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = 0
        self.closed = False

    def post(self, url, json):  # pragma: no cover - exercised via tests
        self.calls += 1
        if not self.responses:
            raise AssertionError("No more stub responses configured")
        next_response = self.responses.pop(0)
        if isinstance(next_response, Exception):
            raise next_response
        return next_response

    def close(self):
        self.closed = True


@pytest.fixture
def stub_httpx_client(monkeypatch):
    """Provide a dummy httpx.Client for tests that don't exercise .post()."""

    dummy = SimpleNamespace(close=lambda: None)
    monkeypatch.setattr(httpx, 'Client', lambda *a, **k: dummy)
    yield


def test_handle_response_maps_status_codes(stub_httpx_client):
    client = HfClient(api_token='token', timeout=1, max_retries=1)

    with pytest.raises(AuthenticationError):
        client._handle_response(FakeResponse(status_code=401))

    with pytest.raises(RateLimitError):
        client._handle_response(FakeResponse(status_code=429))

    with pytest.raises(ModelError):
        client._handle_response(FakeResponse(status_code=503))

    http_error = httpx.HTTPStatusError(
        "boom",
        request=httpx.Request('POST', 'https://example.com'),
        response=httpx.Response(status_code=500),
    )

    with pytest.raises(HfApiError):
        client._handle_response(FakeResponse(status_code=500, raise_error=http_error))

    with pytest.raises(HfApiError):
        client._handle_response(FakeResponse(json_error=ValueError("bad json")))

    client.close()


def test_translate_texts_retries_and_returns(monkeypatch):
    responses = [
        httpx.TimeoutException("timeout"),
        FakeResponse(json_data=[
            {'translation_text': 'Hello'},
            {'translation_text': 'World'}
        ])
    ]

    stub = StubClient(responses)
    monkeypatch.setattr(httpx, 'Client', lambda *a, **k: stub)

    client = HfClient(api_token='token', timeout=1, max_retries=3)
    result = client.translate_texts(['Hallo', 'Welt'], src='de', dst='en')

    assert result == ['Hello', 'World']
    assert stub.calls == 2
    assert stub.closed is False  # Still open until explicit close

    client.close()
    assert stub.closed is True


def test_translate_texts_raises_rate_limit(monkeypatch):
    stub = StubClient([FakeResponse(status_code=429)])
    monkeypatch.setattr(httpx, 'Client', lambda *a, **k: stub)

    client = HfClient(api_token='token', timeout=1, max_retries=1)

    with pytest.raises(RateLimitError):
        client.translate_texts(['Hallo'], src='de', dst='en')

    client.close()
