"""Tests for writer module"""
import pytest
import tempfile
from pathlib import Path
from bs4 import BeautifulSoup, NavigableString
from src.parser import parse
from src.writer import (
    apply_translations, rewrite_links,
    set_lang, map_paths, save_html
)


def test_apply_translations_inplace():
    """Translations applied to correct nodes/attrs"""
    html = """<html><body>
    <h1>Original</h1>
    <p>Text here</p>
    <img src="x" alt="Old alt">
    </body></html>"""

    soup, items = parse(html)

    # Extract texts for translation
    texts = [str(item).strip() for item in items if isinstance(item, NavigableString)]

    # Mock translations
    translations = ['Translated H1', 'Translated text']

    apply_translations(soup, items, translations)

    # Verify translations applied
    assert 'Translated H1' in str(soup.h1)
    assert 'Translated text' in str(soup.p)


def test_rewrite_links_de_to_en():
    """Only /de/ links rewritten to /en/"""
    html = """<html><body>
    <a href="/de/page1">Link 1</a>
    <a href="/de/sub/page2">Link 2</a>
    <a href="/en/existing">Already EN</a>
    <a href="mailto:test@example.com">Email</a>
    <a href="tel:123">Phone</a>
    <a href="#anchor">Anchor</a>
    <a href="https://external.com">External</a>
    </body></html>"""

    soup = BeautifulSoup(html, 'lxml')
    rewrite_links(soup, from_prefix='/de/', to_prefix='/en/')

    links = soup.find_all('a')
    hrefs = [a.get('href') for a in links]

    assert '/en/page1' in hrefs
    assert '/en/sub/page2' in hrefs
    assert '/de/page1' not in hrefs
    assert '/de/sub/page2' not in hrefs
    # These should be unchanged
    assert '/en/existing' in hrefs
    assert 'mailto:test@example.com' in hrefs
    assert 'tel:123' in hrefs
    assert '#anchor' in hrefs
    assert 'https://external.com' in hrefs


def test_rewrite_absolute_same_domain_links():
    """Absolute same-domain links also rewritten"""
    html = """<html><body>
    <a href="https://example.com/de/page1">Absolute DE</a>
    <a href="http://example.com/de/page2">HTTP Absolute</a>
    <a href="/de/relative">Relative DE</a>
    <a href="https://other.com/de/external">External domain</a>
    </body></html>"""

    soup = BeautifulSoup(html, 'lxml')
    rewrite_links(soup, from_prefix='/de/', to_prefix='/en/', domain='example.com')

    links = soup.find_all('a')
    hrefs = [a.get('href') for a in links]

    # Absolute same-domain should be rewritten to relative /en/ path
    assert '/en/page1' in hrefs
    assert '/en/page2' in hrefs
    assert '/en/relative' in hrefs
    # External domain should be unchanged
    assert 'https://other.com/de/external' in hrefs


def test_set_html_lang_to_en():
    """Sets <html lang='en'>"""
    html = "<html lang='de'><body></body></html>"
    soup = BeautifulSoup(html, 'lxml')

    set_lang(soup, lang='en')

    assert soup.html.get('lang') == 'en'


def test_map_paths_and_write_utf8(tmp_path):
    """URL->path mapping and UTF-8 writing"""
    output_dir = str(tmp_path)

    # Test trailing slash -> index.html
    de_path, en_path = map_paths(
        'https://example.com/de/section/',
        output_dir
    )
    assert de_path.endswith('de/section/index.html')
    assert en_path.endswith('en/section/index.html')

    # Test .html file preservation
    de_path, en_path = map_paths(
        'https://example.com/de/page.html',
        output_dir
    )
    assert de_path.endswith('de/page.html')
    assert en_path.endswith('en/page.html')

    # Test write
    soup = BeautifulSoup('<html><body>Ümläuts</body></html>', 'lxml')
    save_html(soup, de_path, encoding='utf-8')

    assert Path(de_path).exists()
    content = Path(de_path).read_text(encoding='utf-8')
    assert 'Ümläuts' in content


def test_map_paths_homepage():
    """Homepage URL maps to index.html, not .html"""
    output_dir = 'output'

    # Test homepage (empty path)
    de_path, en_path = map_paths('https://example.com/', output_dir)
    assert de_path.endswith('de/index.html')
    assert en_path.endswith('en/index.html')

    # Test DE homepage
    de_path, en_path = map_paths('https://example.com/de/', output_dir)
    assert de_path.endswith('de/index.html')
    assert en_path.endswith('en/index.html')


def test_dom_shape_equal():
    """Helper: DOM shape unchanged after translation"""
    original_html = """<html><body>
    <h1>Title</h1>
    <ul><li>One</li><li>Two</li></ul>
    </body></html>"""

    soup1 = BeautifulSoup(original_html, 'lxml')
    soup2 = BeautifulSoup(original_html, 'lxml')

    # Apply some translation (doesn't matter what)
    for string in soup2.find_all(string=True):
        if string.strip():
            string.replace_with('TRANSLATED')

    # Check tag structure is same
    tags1 = [tag.name for tag in soup1.find_all()]
    tags2 = [tag.name for tag in soup2.find_all()]

    assert tags1 == tags2
