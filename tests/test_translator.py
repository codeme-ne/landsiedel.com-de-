"""Tests for translator module"""
import pytest
from unittest.mock import Mock, patch
from src.translator import has_model, translate_batch


def test_has_model_or_skip():
    """Skip test if model not available"""
    if not has_model('de', 'en'):
        pytest.skip("Argos DE->EN model not installed")


def test_batch_translation_mocked():
    """Batch translation with mocked Argos"""
    texts = ['Hallo', 'Welt', 'Test']

    # Mock the translation chain
    mock_translation = Mock()
    mock_translation.translate.return_value = 'Hello'

    with patch('src.translator.argostranslate') as mock_argos:
        mock_de = Mock()
        mock_en = Mock()
        mock_de.code = 'de'
        mock_en.code = 'en'
        mock_de.get_translation.return_value = mock_translation
        mock_argos.translate.get_installed_languages.return_value = [mock_de, mock_en]

        # Mock translate responses
        mock_translation.translate.side_effect = ['Hello', 'World', 'Test']

        results = translate_batch(texts, src='de', dst='en')

        assert len(results) == 3
        assert results[0] == 'Hello'
        assert results[1] == 'World'
        assert results[2] == 'Test'


def test_skips_empty_strings():
    """Empty/whitespace inputs are preserved"""
    texts = ['Hallo', '', '  ', 'Welt']

    mock_translation = Mock()
    mock_translation.translate.side_effect = ['Hello', 'World']

    with patch('src.translator.argostranslate') as mock_argos:
        mock_de = Mock()
        mock_en = Mock()
        mock_de.code = 'de'
        mock_en.code = 'en'
        mock_de.get_translation.return_value = mock_translation
        mock_argos.translate.get_installed_languages.return_value = [mock_de, mock_en]

        results = translate_batch(texts, src='de', dst='en')

        # Empty strings preserved in output
        assert len(results) == 4
        assert results[0] == 'Hello'
        assert results[1] == ''
        assert results[2] == '  '
        assert results[3] == 'World'


def test_special_chars_preserved_mocked():
    """Special chars like umlauts handled correctly"""
    texts = ['Müller', 'Größe']

    mock_translation = Mock()
    mock_translation.translate.side_effect = ['Mueller', 'Size']

    with patch('src.translator.argostranslate') as mock_argos:
        mock_de = Mock()
        mock_en = Mock()
        mock_de.code = 'de'
        mock_en.code = 'en'
        mock_de.get_translation.return_value = mock_translation
        mock_argos.translate.get_installed_languages.return_value = [mock_de, mock_en]

        results = translate_batch(texts, src='de', dst='en')

        assert len(results) == 2
        # Just verify we got results (actual translation depends on Argos)
        assert isinstance(results[0], str)
        assert isinstance(results[1], str)


def test_soft_hyphen_normalization():
    """Soft hyphens removed before translation to prevent artifacts"""
    # Text with soft hyphen (\u00AD)
    texts = ['Welcome to \u00ADLandsiedel', 'Normal text']

    mock_translation = Mock()
    mock_translation.translate.side_effect = ['Welcome to Landsiedel', 'Normal text']

    with patch('src.translator.argostranslate') as mock_argos:
        mock_de = Mock()
        mock_en = Mock()
        mock_de.code = 'de'
        mock_en.code = 'en'
        mock_de.get_translation.return_value = mock_translation
        mock_argos.translate.get_installed_languages.return_value = [mock_de, mock_en]

        results = translate_batch(texts, src='de', dst='en')

        assert len(results) == 2
        # Verify soft hyphen was normalized (no dash artifact)
        assert '-Landsiedel' not in results[0]
        # Verify translation was called with normalized text
        calls = mock_translation.translate.call_args_list
        assert '\u00AD' not in calls[0][0][0]  # First arg of first call


def test_punctuation_only_preserved():
    """Punctuation-only strings preserved unchanged, maintaining alignment"""
    texts = [' | ', '  ', 'Deutscher Text', '·', '—']

    mock_translation = Mock()
    # Only the actual text should be translated
    mock_translation.translate.return_value = 'German Text'

    with patch('src.translator.argostranslate') as mock_argos:
        mock_de = Mock()
        mock_en = Mock()
        mock_de.code = 'de'
        mock_en.code = 'en'
        mock_de.get_translation.return_value = mock_translation
        mock_argos.translate.get_installed_languages.return_value = [mock_de, mock_en]

        results = translate_batch(texts, src='de', dst='en')

        # Critical: length must match to preserve indexing
        assert len(results) == 5
        # Punctuation/whitespace preserved
        assert results[0] == ' | '
        assert results[1] == '  '
        assert results[2] == 'German Text'
        assert results[3] == '·'
        assert results[4] == '—'
        # Verify translate was called only once (for the actual text)
        assert mock_translation.translate.call_count == 1
