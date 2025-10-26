"""HTML parser for extracting translatable content"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Iterable, List

from bs4 import BeautifulSoup, Comment, NavigableString, Tag

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
META_NAME_FIELDS = {'description', 'keywords'}
META_PROPERTY_FIELDS = {
    'og:title',
    'og:description',
    'og:image:alt',
    'twitter:title',
    'twitter:description',
}

JSON_LD_TRANSLATABLE_KEYS = {
    'name',
    'headline',
    'description',
    'text',
    'title',
    'caption',
    'alternateName',
}

SCRIPT_HTML_PATTERN = re.compile(r"html\s*:\s*'((?:\\.|[^'])*)'", re.DOTALL)


@dataclass
class JsonFieldItem:
    """Reference to a string field inside JSON-LD content."""

    script_tag: Tag
    payload: Any
    path: list[Any]

    def get_value(self) -> str:
        value: Any = self.payload
        for key in self.path:
            value = value[key]
        return value

    def set_value(self, new_value: str) -> None:
        target: Any = self.payload
        for key in self.path[:-1]:
            target = target[key]
        target[self.path[-1]] = new_value


@dataclass
class ScriptHtmlContext:
    """Holds information about embedded HTML fragments stored within script tags."""

    script_tag: Tag
    original_text: str
    fragments: list['EmbeddedHtmlFragment'] = field(default_factory=list)

    def commit(self) -> None:
        """Rewrite the script text with updated HTML fragments."""
        if not any(fragment.dirty for fragment in self.fragments):
            return

        fragments = sorted(self.fragments, key=lambda fragment: fragment.start)
        parts: List[str] = []
        cursor = 0

        for fragment in fragments:
            parts.append(self.original_text[cursor:fragment.start])
            parts.append(_escape_js_literal(fragment.render_html()))
            cursor = fragment.end

        parts.append(self.original_text[cursor:])
        new_text = ''.join(parts)

        if self.script_tag.string is None:
            self.script_tag.string = new_text
        else:
            self.script_tag.string.replace_with(new_text)

        self.original_text = new_text
        for fragment in self.fragments:
            fragment.dirty = False


@dataclass
class EmbeddedHtmlFragment:
    """HTML fragment embedded within a JavaScript string literal."""

    context: ScriptHtmlContext
    start: int
    end: int
    soup: BeautifulSoup
    dirty: bool = False

    def render_html(self) -> str:
        return str(self.soup)


@dataclass
class EmbeddedHtmlItem:
    """Reference to a text node or attribute inside an embedded HTML fragment."""

    fragment: EmbeddedHtmlFragment
    node: NavigableString | Tag
    attr: str | None = None

    def get_value(self) -> str:
        if self.attr:
            return self.node[self.attr]
        return str(self.node)


def _escape_js_literal(value: str) -> str:
    """Escape a string so it can be embedded inside a JavaScript single-quoted literal."""
    value = value.replace('\r\n', '\n').replace('\r', '\n')
    escaped = (
        value.replace('\\', '\\\\')
        .replace("'", "\\'")
        .replace('\n', '\\n')
    )
    return escaped


def _decode_js_literal(value: str) -> str:
    """Decode common escape sequences from a JavaScript string literal."""
    result_chars: list[str] = []
    i = 0
    length = len(value)
    while i < length:
        char = value[i]
        if char == "\\" and i + 1 < length:
            nxt = value[i + 1]
            if nxt in {"'", '"', "\\", "/"}:
                result_chars.append(nxt)
                i += 2
                continue
            if nxt == "n":
                result_chars.append("\n")
                i += 2
                continue
            if nxt == "r":
                result_chars.append("\r")
                i += 2
                continue
            if nxt == "t":
                result_chars.append("\t")
                i += 2
                continue
        result_chars.append(char)
        i += 1
    return "".join(result_chars)


def _is_translatable_text_node(string: NavigableString) -> bool:
    if isinstance(string, Comment):
        return False

    text = str(string)
    if not text.strip():
        return False

    if '<' in text:
        return False

    parents = [parent for parent in string.parents if getattr(parent, "name", None)]

    if any(parent.name in EXCLUDED_TAGS for parent in parents):
        return False

    return any(parent.name in ALLOWED_TAGS for parent in parents)


def _collect_fragment_items(fragment: EmbeddedHtmlFragment) -> list[EmbeddedHtmlItem]:
    collected: list[EmbeddedHtmlItem] = []

    for string in fragment.soup.find_all(string=True):
        if isinstance(string, NavigableString) and _is_translatable_text_node(string):
            collected.append(EmbeddedHtmlItem(fragment=fragment, node=string))

    for tag in fragment.soup.find_all(True):
        for attr in TRANSLATABLE_ATTRS:
            if tag.has_attr(attr) and tag[attr].strip():
                collected.append(EmbeddedHtmlItem(fragment=fragment, node=tag, attr=attr))

    return collected


def _collect_json_items(script_tag: Tag, payload: Any) -> list[JsonFieldItem]:
    items: list[JsonFieldItem] = []

    def walk(node: Any, path: list[Any]) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                new_path = path + [key]
                if isinstance(value, str) and value.strip() and key in JSON_LD_TRANSLATABLE_KEYS:
                    items.append(JsonFieldItem(script_tag=script_tag, payload=payload, path=new_path))
                else:
                    walk(value, new_path)
        elif isinstance(node, list):
            for index, value in enumerate(node):
                walk(value, path + [index])

    walk(payload, [])
    return items


def parse(html: str) -> tuple[BeautifulSoup, list]:
    """
    Parse HTML and extract translatable items.

    Returns (soup, items) where items contains:
    - NavigableString references for text nodes
    - (tag, attr_name) tuples for attributes
    """
    soup = BeautifulSoup(html, 'lxml')
    items = []

    # Collect text nodes from allowed tags
    for string in soup.find_all(string=True):
        # Skip real HTML comments
        if isinstance(string, Comment):
            continue
        if not isinstance(string, NavigableString):
            continue
        if _is_translatable_text_node(string):
            items.append(string)

    # Collect translatable attributes
    for tag in soup.find_all(True):  # All tags
        for attr in TRANSLATABLE_ATTRS:
            if tag.has_attr(attr) and tag[attr].strip():
                items.append((tag, attr))

    # Collect meta description/keywords
    for meta in soup.find_all('meta'):
        meta_name = meta.get('name')
        meta_property = meta.get('property')
        if meta_name in META_NAME_FIELDS or meta_property in META_PROPERTY_FIELDS:
            if meta.has_attr('content') and meta['content'].strip():
                items.append((meta, 'content'))

    # Collect JSON-LD content
    for script in soup.find_all('script', attrs={'type': 'application/ld+json'}):
        script_text = script.string
        if not script_text or not script_text.strip():
            continue
        try:
            payload = json.loads(script_text)
        except json.JSONDecodeError:
            continue

        json_items = _collect_json_items(script, payload)
        items.extend(json_items)

    # Collect embedded HTML fragments inside scripts
    for script in soup.find_all('script'):
        script_text = script.string
        if not script_text or not script_text.strip():
            continue

        matches = list(SCRIPT_HTML_PATTERN.finditer(script_text))
        if not matches:
            continue

        context = ScriptHtmlContext(script_tag=script, original_text=script_text)
        for match in matches:
            inner_raw = match.group(1)
            decoded_html = _decode_js_literal(inner_raw)
            fragment_soup = BeautifulSoup(decoded_html, 'lxml')
            fragment = EmbeddedHtmlFragment(
                context=context,
                start=match.start(1),
                end=match.end(1),
                soup=fragment_soup,
            )
            context.fragments.append(fragment)
            items.extend(_collect_fragment_items(fragment))

    return soup, items
