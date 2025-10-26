"""HTML writer with translation application and link rewriting"""
import logging
from pathlib import Path
from urllib.parse import urlparse
from bs4 import BeautifulSoup, NavigableString

logger = logging.getLogger(__name__)


def apply_translations(soup: BeautifulSoup, items: list, translations: list[str]) -> None:
    """
    Apply translations to items in-place.

    Items can be:
    - NavigableString: replace text content
    - (tag, attr_name): set attribute value
    """
    trans_idx = 0

    for item in items:
        if isinstance(item, NavigableString):
            # Text node - preserve leading/trailing whitespace
            if trans_idx < len(translations):
                original = str(item)
                translation = translations[trans_idx]
                
                # Extract whitespace
                leading = len(original) - len(original.lstrip())
                trailing = len(original) - len(original.rstrip())
                
                # Apply whitespace to translation
                if leading > 0:
                    translation = original[:leading] + translation
                if trailing > 0:
                    translation = translation + original[-trailing:]
                
                item.replace_with(translation)
                trans_idx += 1

        elif isinstance(item, tuple):
            # Attribute: (tag, attr_name)
            tag, attr_name = item
            if trans_idx < len(translations):
                tag[attr_name] = translations[trans_idx]
                trans_idx += 1


def rewrite_links(soup: BeautifulSoup, from_prefix: str = '/de/', to_prefix: str = '/en/',
                  domain: str = 'www.landsiedel.com') -> None:
    """
    Rewrite <a href> links from DE to EN paths.

    Handles:
    - Root-relative links: /de/... -> /en/...
    - Absolute same-domain links: https://domain/de/... -> /en/...
    """
    for a in soup.find_all('a', href=True):
        href = a['href']

        # Root-relative link
        if href.startswith(from_prefix):
            a['href'] = href.replace(from_prefix, to_prefix, 1)
        # Absolute same-domain link
        elif href.startswith(f'https://{domain}{from_prefix}') or \
             href.startswith(f'http://{domain}{from_prefix}'):
            # Extract path and rewrite
            parsed = urlparse(href)
            if parsed.path.startswith(from_prefix):
                new_path = parsed.path.replace(from_prefix, to_prefix, 1)
                a['href'] = new_path


def set_lang(soup: BeautifulSoup, lang: str = 'en') -> None:
    """Set <html lang> attribute"""
    if soup.html:
        soup.html['lang'] = lang


def map_paths(url: str, output_dir: str) -> tuple[str, str]:
    """
    Map URL to output file paths for DE and EN versions.

    Rules:
    - Mirror URL path structure
    - Strip /de/ language prefix from path
    - Empty path or trailing slash -> .../index.html
    - Keep .html filenames
    """
    parsed = urlparse(url)
    path = parsed.path

    # Remove leading slash
    if path.startswith('/'):
        path = path[1:]

    # Strip /de/ language prefix if present
    if path.startswith('de/'):
        path = path[3:]  # Remove 'de/'

    # Handle empty path (homepage) or trailing slash
    if not path or path.endswith('/'):
        path = path + 'index.html'
    elif not path.endswith('.html'):
        # Add .html if no extension
        path = path + '.html'

    de_path = str(Path(output_dir) / 'de' / path)
    en_path = str(Path(output_dir) / 'en' / path)

    return de_path, en_path


def save_html(soup: BeautifulSoup, path: str, encoding: str = 'utf-8') -> None:
    """Save HTML to file with UTF-8 encoding"""
    path_obj = Path(path)
    path_obj.parent.mkdir(parents=True, exist_ok=True)

    html = str(soup)
    path_obj.write_text(html, encoding=encoding)

    logger.info(f"Saved {path}")
