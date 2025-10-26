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
from src.parser import parse
from src.translator import translate_batch
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
    """
    tree = etree.parse(path)
    root = tree.getroot()
    
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


def process_single_url(url: str, output_dir: str) -> None:
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
        else:  # NavigableString
            texts_to_translate.append(str(item))
    
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


def run_batch(
    urls: list[str],
    output_dir: str,
    delay: float = 1.0,
    log_file: Optional[str] = None
) -> dict:
    """
    Process multiple URLs from sitemap with error handling and rate limiting.
    
    Args:
        urls: List of URLs to process
        output_dir: Output directory for HTML files
        delay: Delay in seconds between requests (default 1.0)
        log_file: Optional log file path
    
    Returns:
        {
            'success': int,    # Successfully processed
            'failed': int,     # Failed with error
            'skipped': int,    # Skipped (non-HTML/fetch error)
            'failed_urls': [(url, error)]
        }
    """
    # Setup logging
    if log_file:
        handler = logging.FileHandler(log_file)
        handler.setFormatter(logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        ))
        logger.addHandler(handler)
    
    # Counters
    success = 0
    failed = 0
    skipped = 0
    failed_urls = []
    
    total = len(urls)
    logger.info(f"Starting batch processing: {total} URLs")
    
    for i, url in enumerate(urls, start=1):
        logger.info(f"[{i}/{total}] Processing: {url}")
        
        try:
            process_single_url(url, output_dir)
            success += 1
            logger.info(f"[{i}/{total}] Success")
            
        except FetchError as e:
            # HTTP errors, timeouts → skip
            skipped += 1
            logger.warning(f"[{i}/{total}] Skipped (fetch error): {e}")
            
        except Exception as e:
            # Parse/translation/write errors → fail
            failed += 1
            error_msg = str(e)
            failed_urls.append((url, error_msg))
            logger.error(f"[{i}/{total}] Failed: {e}", exc_info=True)
        
        # Rate limiting (skip delay after last URL)
        if i < total:
            time.sleep(delay)
    
    # Write failed_urls.txt if there were failures
    if failed_urls:
        failed_path = Path(output_dir) / 'failed_urls.txt'
        with open(failed_path, 'w', encoding='utf-8') as f:
            f.write(f"# Failed URLs ({datetime.now().strftime('%Y-%m-%d %H:%M:%S')})\n")
            for url, error in failed_urls:
                f.write(f"{url} | Error: {error}\n")
        logger.info(f"Failed URLs written to: {failed_path}")
    
    # Summary
    logger.info("=" * 60)
    logger.info("BATCH PROCESSING COMPLETE")
    logger.info(f"  Processed: {total}")
    logger.info(f"  Success:   {success}")
    logger.info(f"  Failed:    {failed}")
    logger.info(f"  Skipped:   {skipped}")
    logger.info("=" * 60)
    
    return {
        'success': success,
        'failed': failed,
        'skipped': skipped,
        'failed_urls': failed_urls
    }
