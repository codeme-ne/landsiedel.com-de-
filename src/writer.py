"""HTML writer with translation application and link rewriting"""
import json
import logging
import re
from pathlib import Path
from urllib.parse import urlparse
from bs4 import BeautifulSoup, NavigableString

from src.parser import EmbeddedHtmlItem, JsonFieldItem, ScriptHtmlContext

logger = logging.getLogger(__name__)


def _replace_text_node(node: NavigableString, translation: str) -> None:
    """Replace a NavigableString while preserving leading/trailing whitespace."""
    original = str(node)
    leading = len(original) - len(original.lstrip())
    trailing = len(original) - len(original.rstrip())

    result = translation
    if leading > 0:
        result = original[:leading] + result
    if trailing > 0:
        result = result + original[-trailing:]

    node.replace_with(result)


def apply_translations(soup: BeautifulSoup, items: list, translations: list[str]) -> None:
    """
    Apply translations to items in-place.

    Items can be:
    - NavigableString: replace text content
    - (tag, attr_name): set attribute value
    - JsonFieldItem: update JSON-LD payloads
    - EmbeddedHtmlItem: update HTML fragments embedded in scripts
    """
    trans_idx = 0
    json_contexts: dict[int, JsonFieldItem] = {}
    fragment_contexts: dict[int, ScriptHtmlContext] = {}

    for item in items:
        if isinstance(item, NavigableString):
            # Text node - preserve leading/trailing whitespace
            if trans_idx < len(translations):
                _replace_text_node(item, translations[trans_idx])
                trans_idx += 1

        elif isinstance(item, tuple):
            # Attribute: (tag, attr_name)
            tag, attr_name = item
            if trans_idx < len(translations):
                tag[attr_name] = translations[trans_idx]
                trans_idx += 1

        elif isinstance(item, JsonFieldItem):
            if trans_idx < len(translations):
                item.set_value(translations[trans_idx])
                json_contexts[id(item.payload)] = item
                trans_idx += 1

        elif isinstance(item, EmbeddedHtmlItem):
            if trans_idx < len(translations):
                translation = translations[trans_idx]
                if item.attr:
                    item.node[item.attr] = translation
                else:
                    _replace_text_node(item.node, translation)
                item.fragment.dirty = True
                fragment_contexts[id(item.fragment.context)] = item.fragment.context
                trans_idx += 1

    # Persist JSON-LD updates
    for json_item in json_contexts.values():
        serialized = json.dumps(json_item.payload, ensure_ascii=False, indent=2)
        if json_item.script_tag.string is None:
            json_item.script_tag.string = serialized
        else:
            json_item.script_tag.string.replace_with(serialized)

    # Persist embedded HTML fragment updates
    for context in fragment_contexts.values():
        context.commit()


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


def _validate_safe_path(path: str, output_base: Path) -> None:
    """
    Validate that a path is safe and does not traverse outside output directory.

    Raises:
        ValueError: If path contains traversal attempts or unsafe characters
    """
    # Check for '..' in path components
    path_obj = Path(path)
    if '..' in path_obj.parts:
        raise ValueError(f"Path traversal detected: path contains '..' component")

    # Validate path contains only safe characters
    safe_pattern = re.compile(r'^[a-zA-Z0-9/_.-]+$')
    if not safe_pattern.match(str(path_obj)):
        raise ValueError(f"Path contains unsafe characters: {path}")

    # Resolve to absolute path and verify it starts with output_base
    try:
        resolved = (output_base / path_obj).resolve()
        base_resolved = output_base.resolve()

        # Check if resolved path is within output directory
        if not str(resolved).startswith(str(base_resolved)):
            raise ValueError(f"Path traversal detected: {path} resolves outside output directory")
    except (ValueError, OSError) as e:
        raise ValueError(f"Invalid path: {path}") from e


def map_paths(url: str, output_dir: str) -> tuple[str, str]:
    """
    Map URL to output file paths for DE and EN versions.

    Rules:
    - Mirror URL path structure
    - Strip /de/ language prefix from path
    - Empty path or trailing slash -> .../index.html
    - Keep .html filenames

    Security:
    - Validates against path traversal attacks
    - Ensures output stays within output_dir
    - Blocks paths with '..' components
    - Validates safe characters only

    Raises:
        ValueError: If URL path contains traversal attempts or unsafe characters
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

    # Validate path safety BEFORE constructing final paths
    output_base = Path(output_dir)
    _validate_safe_path(path, output_base)

    de_path = str(output_base / 'de' / path)
    en_path = str(output_base / 'en' / path)

    return de_path, en_path


def save_html(soup: BeautifulSoup, path: str, encoding: str = 'utf-8') -> None:
    """Save HTML to file with UTF-8 encoding"""
    path_obj = Path(path)
    path_obj.parent.mkdir(parents=True, exist_ok=True)

    html = str(soup)
    path_obj.write_text(html, encoding=encoding)

    logger.info(f"Saved {path}")
