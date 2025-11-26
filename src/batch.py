#!/usr/bin/env python3
"""Batch processing for sitemap-based translations"""
import json
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

from lxml import etree

from src.fetcher import fetch, FetchError
from src.parser import EmbeddedHtmlItem, JsonFieldItem, parse
from src.translator import preview_batch, translate_batch
from src.writer import (
    apply_translations, rewrite_links,
    set_lang, map_paths, save_html
)

logger = logging.getLogger(__name__)

SITEMAP_NAMESPACE = {'sm': 'http://www.sitemaps.org/schemas/sitemap/0.9'}


def load_sitemap_json(path: str) -> list[str]:
    """
    Load URLs from sitemap.json.
    
    Expects: Array of objects with 'url' or 'loc' field.
    Filters: Only /de/ URLs from www.landsiedel.com
    Returns: Deduplicated list of URLs
    """
    with open(path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    if not isinstance(data, list):
        raise ValueError("sitemap.json must contain an array")
    
    urls = set()
    for item in data:
        if not isinstance(item, dict):
            continue
        url = item.get('url') or item.get('loc')
        if url:
            urls.add(url)
    
    # Filter: only /de/ URLs from www.landsiedel.com
    filtered = []
    for url in urls:
        parsed = urlparse(url)
        if parsed.netloc == 'www.landsiedel.com' and '/de/' in parsed.path:
            filtered.append(url)
    
    return sorted(filtered)


def load_sitemap_xml(path: str) -> list[str]:
    """
    Load URLs from sitemap.xml.

    Handles standard sitemap.org schema with namespaces.
    Filters: Only /de/ URLs from www.landsiedel.com
    Returns: Deduplicated list of URLs
    Raises: etree.XMLSyntaxError if XML is malformed or contains unsafe entities
    """
    # Create secure parser to prevent XXE attacks
    parser = etree.XMLParser(
        resolve_entities=False,  # Disable external entity resolution
        no_network=True,         # Block network access
        dtd_validation=False,    # Disable DTD validation
        load_dtd=False           # Do not load DTDs
    )

    try:
        tree = etree.parse(path, parser)
        root = tree.getroot()
    except etree.XMLSyntaxError as e:
        logger.error(f"XML parsing failed for {path}: {e}")
        raise
    
    # Extract URLs (namespace-safe)
    urls = set()
    for loc in root.xpath('//sm:loc/text()', namespaces=SITEMAP_NAMESPACE):
        urls.add(loc)
    
    # Fallback: try without namespace
    if not urls:
        for loc in root.xpath('//loc/text()'):
            urls.add(loc)
    
    # Filter: only /de/ URLs from www.landsiedel.com
    filtered = []
    for url in urls:
        parsed = urlparse(url)
        if parsed.netloc == 'www.landsiedel.com' and '/de/' in parsed.path:
            filtered.append(url)
    
    return sorted(filtered)


def load_sitemap(path: str) -> list[str]:
    """
    Auto-detect and load sitemap (JSON or XML).
    
    Strategy:
    1. Check file extension (.json → JSON, .xml → XML)
    2. Fallback: Try JSON first, then XML
    
    Returns: Deduplicated, filtered list of URLs
    Raises: ValueError if both formats fail
    """
    path_obj = Path(path)
    if not path_obj.exists():
        raise FileNotFoundError(f"Sitemap not found: {path}")
    
    # Try by extension
    if path.endswith('.json'):
        return load_sitemap_json(path)
    elif path.endswith('.xml'):
        return load_sitemap_xml(path)
    
    # Fallback: try both
    try:
        return load_sitemap_json(path)
    except (json.JSONDecodeError, ValueError):
        pass
    
    try:
        return load_sitemap_xml(path)
    except etree.XMLSyntaxError:
        pass
    
    raise ValueError(f"Could not parse {path} as JSON or XML sitemap")


def process_single_url(url: str, output_dir: str, dry_run: bool = False) -> Optional[dict]:
    """
    Process single URL through the translation pipeline.

    Pipeline:
    1. Fetch HTML
    2. Parse translatable items
    3. Translate DE → EN
    4. Apply translations
    5. Rewrite /de/ → /en/ links
    6. Set lang="en"
    7. Save DE original + EN translated

    When ``dry_run`` is True, the function returns a summary dictionary and
    stops before translation and write steps.

    Raises: FetchError for HTTP issues, Exception for other errors
    """
    # Fetch
    html, meta = fetch(url)
    
    # Parse
    soup, items = parse(html)
    
    # Extract texts
    texts_to_translate = []
    for item in items:
        if isinstance(item, tuple):  # (tag, attr)
            tag, attr = item
            texts_to_translate.append(tag[attr])
        elif isinstance(item, JsonFieldItem):
            texts_to_translate.append(item.get_value())
        elif isinstance(item, EmbeddedHtmlItem):
            texts_to_translate.append(item.get_value())
        else:  # NavigableString
            texts_to_translate.append(str(item))
    
    if dry_run:
        plan = preview_batch(texts_to_translate, src='de', dst='en')
        logger.info("Dry run summary for %s", url)
        logger.info("  Total texts: %d", plan.total)
        logger.info("  Cache hits: %d", plan.cache_hits)
        logger.info("  Pending translations: %d", len(plan.pending))

        for item in plan.pending[:5]:
            snippet = str(item.original).strip().replace('\n', ' ')
            if len(snippet) > 60:
                snippet = snippet[:57] + '...'
            logger.info("    - idx %d: %s", item.index, snippet)

        if len(plan.pending) > 5:
            logger.info("    ... %d additional texts", len(plan.pending) - 5)

        return {
            'url': url,
            'total_texts': plan.total,
            'cache_hits': plan.cache_hits,
            'pending_translations': len(plan.pending)
        }

    # Translate
    translations = translate_batch(texts_to_translate, src='de', dst='en')
    
    # Apply translations
    apply_translations(soup, items, translations)
    
    # Rewrite links
    domain = urlparse(meta['final_url']).netloc
    rewrite_links(soup, from_prefix='/de/', to_prefix='/en/', domain=domain)
    
    # Set language
    set_lang(soup, lang='en')
    
    # Map output paths
    de_path, en_path = map_paths(meta['final_url'], output_dir)
    
    # Save original DE version (re-parse for clean copy)
    de_soup, _ = parse(html)
    save_html(de_soup, de_path)
    
    # Save translated EN version
    save_html(soup, en_path)
    
    logger.info(f"  Saved: {de_path}")
    logger.info(f"  Saved: {en_path}")

    return None


def run_batch(
    urls: list[str],
    output_dir: str,
    delay: float = 1.0,
    log_file: Optional[str] = None,
    dry_run: bool = False
) -> dict:
    """
    Process multiple URLs from a sitemap with error handling and rate limiting.

    Args:
        urls: List of URLs to process
        output_dir: Output directory for HTML files
        delay: Delay in seconds between requests (default 1.0)
        log_file: Optional log file path
        dry_run: When True, plan translations without calling the backend

    Returns:
        {
            'success': int,
            'failed': int,
            'skipped': int,
            'failed_urls': [(url, error)],
            'dry_run': { ... }  # only present when dry_run=True
        }
    """

    if log_file:
        handler = logging.FileHandler(log_file)
        handler.setFormatter(logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        ))
        logger.addHandler(handler)

    success = 0
    failed = 0
    skipped = 0
    failed_urls: list[tuple[str, str]] = []
    dry_stats = {
        'urls': 0,
        'total_texts': 0,
        'cache_hits': 0,
        'pending_translations': 0
    } if dry_run else None

    total = len(urls)
    logger.info(f"Starting batch processing: {total} URLs (dry-run={dry_run})")

    for i, url in enumerate(urls, start=1):
        logger.info(f"[{i}/{total}] Processing: {url}")

        try:
            summary = process_single_url(url, output_dir, dry_run=dry_run)
            success += 1
            logger.info(f"[{i}/{total}] Success")

            if dry_stats is not None and summary:
                dry_stats['urls'] += 1
                dry_stats['total_texts'] += summary['total_texts']
                dry_stats['cache_hits'] += summary['cache_hits']
                dry_stats['pending_translations'] += summary['pending_translations']

        except FetchError as exc:
            skipped += 1
            logger.warning(f"[{i}/{total}] Skipped (fetch error): {exc}")

        except Exception as exc:
            failed += 1
            error_msg = str(exc)
            failed_urls.append((url, error_msg))
            logger.error(f"[{i}/{total}] Failed: {exc}", exc_info=True)

        if i < total:
            time.sleep(delay)

    if failed_urls:
        failed_path = Path(output_dir) / 'failed_urls.txt'
        with open(failed_path, 'w', encoding='utf-8') as fh:
            fh.write(f"# Failed URLs ({datetime.now().strftime('%Y-%m-%d %H:%M:%S')})\n")
            for entry_url, error in failed_urls:
                fh.write(f"{entry_url} | Error: {error}\n")
        logger.info(f"Failed URLs written to: {failed_path}")

    logger.info("=" * 60)
    logger.info("BATCH PROCESSING COMPLETE")
    logger.info(f"  Processed: {total}")
    logger.info(f"  Success:   {success}")
    logger.info(f"  Failed:    {failed}")
    logger.info(f"  Skipped:   {skipped}")

    if dry_stats is not None and dry_stats['urls']:
        logger.info(
            "  Dry-run: %d URLs, %d texts, %d pending (cache hits: %d)",
            dry_stats['urls'],
            dry_stats['total_texts'],
            dry_stats['pending_translations'],
            dry_stats['cache_hits']
        )

    logger.info("=" * 60)

    result = {
        'success': success,
        'failed': failed,
        'skipped': skipped,
        'failed_urls': failed_urls,
    }

    if dry_stats is not None:
        result['dry_run'] = dry_stats

    return result
