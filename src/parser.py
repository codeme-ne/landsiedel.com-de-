"""HTML parser for extracting translatable content"""
import re
from bs4 import BeautifulSoup, NavigableString, Comment

# Tags whose text content should be translated
ALLOWED_TAGS = {
    'title',
    'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
    'p', 'li', 'a', 'span', 'strong', 'em',
    'blockquote', 'td', 'th', 'figcaption', 'button'
}

# Tags to exclude from text extraction
EXCLUDED_TAGS = {'script', 'style', 'code', 'pre', 'noscript'}

# Attributes to translate
TRANSLATABLE_ATTRS = {'alt', 'title'}


def parse(html: str) -> tuple[BeautifulSoup, list]:
    """
    Parse HTML and extract translatable items.

    Returns (soup, items) where items contains:
    - NavigableString references for text nodes
    - (tag, attr_name) tuples for attributes
    """
    soup = BeautifulSoup(html, 'lxml')
    items = []

    # Regex to detect text that looks like HTML or entities
    html_like_pattern = re.compile(r'&\w+;|<|>')

    # Collect text nodes from allowed tags
    for string in soup.find_all(string=True):
        # Skip real HTML comments
        if isinstance(string, Comment):
            continue
        if not isinstance(string, NavigableString):
            continue

        # Skip text that looks like HTML (entities or angle brackets)
        if html_like_pattern.search(str(string)):
            continue

        # Skip whitespace-only content
        if not string.strip():
            continue

        # Skip if inside an excluded tag anywhere in the ancestry
        if any(parent.name in EXCLUDED_TAGS for parent in string.parents if getattr(parent, "name", None)):
            continue

        # Include if any ancestor (including direct parent) is in allowed tags
        if any(parent.name in ALLOWED_TAGS for parent in string.parents if getattr(parent, "name", None)):
            items.append(string)

    # Collect translatable attributes
    for tag in soup.find_all(True):  # All tags
        for attr in TRANSLATABLE_ATTRS:
            if tag.has_attr(attr) and tag[attr].strip():
                items.append((tag, attr))

    # Collect meta description/keywords
    for meta in soup.find_all('meta'):
        if meta.get('name') in ('description', 'keywords'):
            if meta.has_attr('content') and meta['content'].strip():
                items.append((meta, 'content'))

    return soup, items
