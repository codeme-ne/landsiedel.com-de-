"""Unit tests for the SQLite-backed translation cache."""

from src.cache import TranslationCache


def test_cache_set_and_get_many(tmp_path):
    cache_path = tmp_path / "cache.db"
    cache = TranslationCache(str(cache_path))

    cache.set_many({'Hallo': 'Hello'}, src='de', dst='en', model='test-model')

    result = cache.get_many(['Hallo'], src='de', dst='en', model='test-model')

    assert result['Hallo'] == 'Hello'


def test_cache_get_many_returns_none_for_misses(tmp_path):
    cache_path = tmp_path / "cache.db"
    cache = TranslationCache(str(cache_path))

    cache.set_many({'Hallo': 'Hello'}, src='de', dst='en', model='test-model')

    result = cache.get_many(['Hallo', 'Welt'], src='de', dst='en', model='test-model')

    assert result['Hallo'] == 'Hello'
    assert result['Welt'] is None


def test_cache_clear_removes_entries(tmp_path):
    cache_path = tmp_path / "cache.db"
    cache = TranslationCache(str(cache_path))

    cache.set_many({'Hallo': 'Hello'}, src='de', dst='en', model='test-model')
    cache.clear()

    result = cache.get_many(['Hallo'], src='de', dst='en', model='test-model')

    assert result['Hallo'] is None
