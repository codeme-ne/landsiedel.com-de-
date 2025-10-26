"""Integration test with real Hugging Face backend (optional)."""
import pytest
from pathlib import Path
from unittest.mock import Mock, patch
from src.translator import has_model
from src.parser import parse
from src.translator import translate_batch
from src.writer import apply_translations, rewrite_links, set_lang


FIXTURE_PATH = Path(__file__).parent / 'fixtures' / 'sample_de.html'


@pytest.mark.skipif(
    not has_model('de', 'en'),
    reason="HF translation backend unavailable"
)
def test_end_to_end_with_real_hf():
    """Full pipeline with real Hugging Face translation backend."""
    # Load fixture
    with open(FIXTURE_PATH, 'r', encoding='utf-8') as f:
        html = f.read()

    # Parse
    soup, items = parse(html)

    # Extract translatable texts (text nodes + attrs)
    texts_to_translate = []
    for item in items:
        if hasattr(item, 'strip'):  # NavigableString
            texts_to_translate.append(str(item).strip())
        elif isinstance(item, tuple):  # (tag, attr)
            tag, attr = item
            texts_to_translate.append(tag[attr])

    # Translate
    translations = translate_batch(texts_to_translate, src='de', dst='en')

    # Apply
    apply_translations(soup, items, translations)
    rewrite_links(soup, from_prefix='/de/', to_prefix='/en/')
    set_lang(soup, lang='en')

    # Verify
    html_out = str(soup)

    # Check lang attribute
    assert 'lang="en"' in html_out or "lang='en'" in html_out

    # Check links rewritten
    assert '/en/page' in html_out
    assert '/de/page' not in html_out


def test_end_to_end_mocked_fetcher_and_translator():
    """Integration test with mocked fetcher and translator"""
    # Mock HTML fetch
    mock_html = """<html lang="de"><body>
    <h1>Hallo</h1>
    <p>Willkommen</p>
    <a href="/de/page">Link</a>
    </body></html>"""

    # Parse
    soup, items = parse(mock_html)

    # Extract texts
    texts = []
    for item in items:
        if hasattr(item, 'strip'):
            texts.append(str(item).strip())
        elif isinstance(item, tuple):
            tag, attr = item
            if tag.has_attr(attr):
                texts.append(tag[attr])

    # Mock translations
    mock_translations = ['Hello', 'Welcome']

    # Apply
    apply_translations(soup, items, mock_translations)
    rewrite_links(soup, from_prefix='/de/', to_prefix='/en/')
    set_lang(soup, lang='en')

    html_out = str(soup)

    # Verify structure and content
    assert 'lang="en"' in html_out or "lang='en'" in html_out
    assert '/en/page' in html_out
    assert 'Hello' in html_out
    assert 'Welcome' in html_out
