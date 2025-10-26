"""Tests for parser module"""
import pytest
from pathlib import Path
from bs4 import BeautifulSoup, NavigableString
from src.parser import parse


FIXTURE_PATH = Path(__file__).parent / 'fixtures' / 'sample_de.html'


def test_extracts_visible_texts():
    """Extracts text from allowed tags"""
    with open(FIXTURE_PATH, 'r', encoding='utf-8') as f:
        html = f.read()

    soup, items = parse(html)

    # Collect text items
    texts = [
        item.strip() for item in items
        if isinstance(item, NavigableString)
    ]

    assert 'Willkommen' in texts
    assert 'Dies ist ein' in texts  # p tag content (partial)
    assert 'Test' in texts  # strong tag
    assert 'Erster Punkt' in texts
    assert 'Zweiter Punkt' in texts
    assert 'Link' in texts  # a tag
    assert 'Ein Zitat über Technologie.' in texts  # blockquote


def test_collects_attributes():
    """Collects alt, title, and meta content attributes"""
    with open(FIXTURE_PATH, 'r', encoding='utf-8') as f:
        html = f.read()

    soup, items = parse(html)

    # Collect attribute items (tag, attr_name) tuples
    attr_items = [
        item for item in items
        if isinstance(item, tuple)
    ]

    # Check img alt
    img_alts = [
        item for item in attr_items
        if item[0].name == 'img' and item[1] == 'alt'
    ]
    assert len(img_alts) > 0
    assert img_alts[0][0]['alt'] == 'Ein Bild'

    # Check a title
    a_titles = [
        item for item in attr_items
        if item[0].name == 'a' and item[1] == 'title'
    ]
    assert len(a_titles) > 0

    # Check meta description
    meta_desc = [
        item for item in attr_items
        if item[0].name == 'meta' and item[1] == 'content'
        and item[0].get('name') == 'description'
    ]
    assert len(meta_desc) > 0


def test_excludes_non_textual_nodes():
    """Excludes text from script, style, code, pre, noscript"""
    with open(FIXTURE_PATH, 'r', encoding='utf-8') as f:
        html = f.read()

    soup, items = parse(html)

    texts = [
        str(item) for item in items
        if isinstance(item, NavigableString)
    ]

    # These should NOT be in the items list
    assert "console.log" not in ' '.join(texts)
    assert ".test { color: red; }" not in ' '.join(texts)
    assert "const x = 42" not in ' '.join(texts)
    assert "JavaScript erforderlich" not in ' '.join(texts)


def test_preserves_dom_shape():
    """Parsing doesn't modify DOM structure"""
    with open(FIXTURE_PATH, 'r', encoding='utf-8') as f:
        html = f.read()

    soup, items = parse(html)

    # Check basic structure still intact
    assert soup.h1 is not None
    assert soup.p is not None
    assert soup.ul is not None
    assert len(soup.find_all('li')) == 2
    assert soup.a is not None
    assert soup.img is not None
