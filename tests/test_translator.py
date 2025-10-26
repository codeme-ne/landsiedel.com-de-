"""Unit tests for translator helpers and batching/caching behaviour."""

import pytest

from src import translator
from src.hf_client import AuthenticationError
from src.translator import (
    _normalize_text,
    _is_punctuation_only,
    _looks_english,
    translate_batch,
    has_model
)


@pytest.fixture(autouse=True)
def reset_translator_cache():
    """Ensure translator cache is reset between tests."""
    translator._cache = None
    translator._ARGOS_TRANSLATORS.clear()
    yield
    translator._cache = None
    translator._ARGOS_TRANSLATORS.clear()


@pytest.fixture(autouse=True)
def force_hf_backend(monkeypatch):
    """Default all tests to the HF backend unless overridden explicitly."""
    monkeypatch.setenv('TRANSLATOR_BACKEND', 'hf')
    yield


class TestNormalizeText:
    """Tests for _normalize_text()"""

    def test_soft_hyphen_removal(self):
        """Should remove soft hyphens (U+00AD)"""
        text = "inter\u00ADesting"
        assert _normalize_text(text) == "interesting"

    def test_zero_width_space_removal(self):
        """Should remove zero-width spaces (U+200B)"""
        text = "hello\u200Bworld"
        assert _normalize_text(text) == "helloworld"

    def test_multiple_invisible_chars(self):
        """Should remove all invisible characters"""
        text = "a\u00ADb\u200Bc\u200Cd\u200De"
        assert _normalize_text(text) == "abcde"

    def test_regular_text_unchanged(self):
        """Should not modify regular text"""
        text = "Hello World!"
        assert _normalize_text(text) == "Hello World!"


class TestIsPunctuationOnly:
    """Tests for _is_punctuation_only()"""

    def test_empty_string(self):
        """Empty string should be considered punctuation-only"""
        assert _is_punctuation_only("") is True

    def test_whitespace_only(self):
        """Whitespace-only should be considered punctuation-only"""
        assert _is_punctuation_only("   ") is True
        assert _is_punctuation_only("\t\n") is True

    def test_single_separator(self):
        """Single separator chars should return True"""
        assert _is_punctuation_only("•") is True
        assert _is_punctuation_only("|") is True
        assert _is_punctuation_only("·") is True

    def test_multiple_separators(self):
        """Multiple separator chars should return True"""
        assert _is_punctuation_only("• | •") is True
        assert _is_punctuation_only("---") is True

    def test_text_with_letters(self):
        """Text with letters should return False"""
        assert _is_punctuation_only("• Hello") is False
        assert _is_punctuation_only("Test |") is False


class TestLooksEnglish:
    """Tests for _looks_english()"""

    def test_simple_english_sentence(self):
        """Simple English sentences should return True"""
        assert _looks_english("This is a test") is True
        assert _looks_english("The quick brown fox") is True

    def test_non_ascii_returns_false(self):
        """Non-ASCII text should return False"""
        assert _looks_english("Hallo Welt") is False
        assert _looks_english("Привет") is False

    def test_no_stopwords_returns_false(self):
        """Text without stopwords should return False"""
        assert _looks_english("xyz") is False
        assert _looks_english("qwerty") is False

    def test_english_with_punctuation(self):
        """English with common punctuation should work"""
        assert _looks_english("The, world!") is True
        assert _looks_english("Is it ready?") is True

    def test_numbers_with_stopwords(self):
        """Numbers with stopwords should return True"""
        assert _looks_english("The number is 42") is True


class TestTranslateBatch:
    """Tests covering batching, caching, and error handling."""

    def test_translate_batch_groups_texts_and_preserves_order(self, monkeypatch, tmp_path):
        monkeypatch.setattr(translator, 'CACHE_ENABLED', True)
        monkeypatch.setattr(translator, 'CACHE_PATH', str(tmp_path / 'cache.db'))
        monkeypatch.setattr(translator, 'BATCH_SIZE', 3)
        monkeypatch.setattr(translator, 'MAX_TOKENS_PER_BATCH', 3)
        calls = []

        class FakeClient:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def translate_texts(self, texts, src, dst):
                calls.append(list(texts))
                return [f"{text}-en" for text in texts]

        monkeypatch.setattr(translator, 'has_model', lambda s, d: True)
        monkeypatch.setattr(translator, 'HfClient', lambda *a, **k: FakeClient())

        texts = [
            "\u00ADHallo",   # Contains soft hyphen → normalization
            "   ",          # Skipped whitespace
            "•",            # Skipped punctuation
            "The header",  # Skipped by heuristic (contains stopword)
            "Welt",
            "Freunde"
        ]

        result = translate_batch(texts, src='de', dst='en')

        assert result == [
            "Hallo-en",
            "   ",
            "•",
            "The header",
            "Welt-en",
            "Freunde-en"
        ]
        # Two calls expected: first contains "Hallo" and "Welt", second "Freunde"
        assert len(calls) == 2
        assert calls[0] == ["Hallo", "Welt"]
        assert calls[1] == ["Freunde"]

    def test_translate_batch_updates_and_reads_cache(self, monkeypatch, tmp_path):
        cache_path = str(tmp_path / 'translations.db')
        monkeypatch.setattr(translator, 'CACHE_ENABLED', True)
        monkeypatch.setattr(translator, 'CACHE_PATH', cache_path)
        monkeypatch.setattr(translator, 'BATCH_SIZE', 3)
        monkeypatch.setattr(translator, 'MAX_TOKENS_PER_BATCH', 6)

        class FakeClient:
            def __init__(self):
                self.calls = 0

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def translate_texts(self, texts, src, dst):
                self.calls += 1
                return [f"{text}-en" for text in texts]

        fake_client = FakeClient()

        monkeypatch.setattr(translator, 'has_model', lambda s, d: True)
        monkeypatch.setattr(translator, 'HfClient', lambda *a, **k: fake_client)

        inputs = ["Freund", "Freund"]

        first = translate_batch(inputs, src='de', dst='en')
        second = translate_batch(inputs, src='de', dst='en')

        assert first == ["Freund-en", "Freund-en"]
        assert second == first
        assert fake_client.calls == 1, "Cache should avoid the second API call"

    def test_translate_batch_handles_short_responses(self, monkeypatch, tmp_path):
        monkeypatch.setattr(translator, 'CACHE_ENABLED', True)
        monkeypatch.setattr(translator, 'CACHE_PATH', str(tmp_path / 'cache.db'))
        monkeypatch.setattr(translator, 'BATCH_SIZE', 3)
        monkeypatch.setattr(translator, 'MAX_TOKENS_PER_BATCH', 6)
        class FakeClient:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def translate_texts(self, texts, src, dst):
                # Return fewer translations than requested to trigger fallback
                return [f"{texts[0]}-en"]

        monkeypatch.setattr(translator, 'has_model', lambda s, d: True)
        monkeypatch.setattr(translator, 'HfClient', lambda *a, **k: FakeClient())

        texts = ["Hallo", "Welt"]
        result = translate_batch(texts, src='de', dst='en')

        assert result == ["Hallo-en", "Welt"], "Short response should fall back to original"

    def test_translate_batch_dry_run_skips_backend(self, monkeypatch):
        def _should_not_call(*args, **kwargs):  # pragma: no cover - guard path
            raise AssertionError("should not call has_model")

        monkeypatch.setattr(translator, 'has_model', _should_not_call)

        class FailContext:
            def __enter__(self):  # pragma: no cover - guard path
                raise AssertionError("should not enter translation context during dry-run")

            def __exit__(self, exc_type, exc, tb):
                return False

        monkeypatch.setattr(translator, '_translation_callable', lambda *a, **k: FailContext())

        texts = ["Hallo", "Welt"]
        result = translate_batch(texts, src='de', dst='en', dry_run=True)

        assert result == texts, "Dry-run should return originals without translation"

    def test_translate_batch_argos_backend(self, monkeypatch):
        class FakeArgosTranslator:
            def __init__(self):
                self.calls = []

            def translate(self, text):
                self.calls.append(text)
                return f"{text}-en"

        fake_translator = FakeArgosTranslator()
        monkeypatch.setenv('TRANSLATOR_BACKEND', 'argos')
        monkeypatch.setattr(translator, '_load_argos_translator', lambda s, d: fake_translator)

        texts = ["Hallo", "Welt"]
        result = translate_batch(texts, src='de', dst='en')

        assert result == ["Hallo-en", "Welt-en"]
        assert fake_translator.calls == ["Hallo", "Welt"]


class TestHasModel:
    """Targeted tests for has_model() around the HF client."""

    def test_has_model_false_on_authentication_error(self, monkeypatch):
        monkeypatch.setenv('TRANSLATOR_BACKEND', 'hf')

        def _raise_auth(*args, **kwargs):
            raise AuthenticationError("bad token")

        monkeypatch.setattr(translator, 'HfClient', _raise_auth)
        assert has_model('de', 'en') is False

    def test_has_model_uses_health_check(self, monkeypatch):
        monkeypatch.setenv('TRANSLATOR_BACKEND', 'hf')

        class FakeClient:
            def __init__(self, *args, **kwargs):
                self.used = False

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def health_check(self, src, dst):
                self.used = True
                return True

        fake_client = FakeClient()
        monkeypatch.setattr(translator, 'HfClient', lambda *a, **k: fake_client)

        assert has_model('de', 'en') is True
        assert fake_client.used is True

    def test_has_model_argos_true_when_translator_available(self, monkeypatch):
        monkeypatch.setenv('TRANSLATOR_BACKEND', 'argos')
        monkeypatch.setattr(translator, '_load_argos_translator', lambda s, d: object())

        assert has_model('de', 'en') is True

    def test_has_model_argos_false_when_translator_missing(self, monkeypatch):
        monkeypatch.setenv('TRANSLATOR_BACKEND', 'argos')
        monkeypatch.setattr(translator, '_load_argos_translator', lambda s, d: None)

        assert has_model('de', 'en') is False
