#!/usr/bin/env python3
"""CLI for website translation pipeline"""
import argparse
import logging
import sys
from pathlib import Path

from src.fetcher import fetch, FetchError
from src.parser import parse
from src.translator import translate_batch, has_model
from src.writer import (
    apply_translations, rewrite_links,
    set_lang, map_paths, save_html
)
from src import batch

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

# Suppress noisy library loggers (including sub-loggers)
logging.getLogger('argostranslate').setLevel(logging.WARNING)
logging.getLogger('argostranslate.utils').setLevel(logging.WARNING)
logging.getLogger('stanza').setLevel(logging.WARNING)

logger = logging.getLogger(__name__)


def main():
    """Main CLI entry point"""
    parser = argparse.ArgumentParser(
        description='Translate German website pages to English'
    )
    parser.add_argument(
        '--url',
        help='URL to fetch and translate (mutually exclusive with --sitemap)'
    )
    parser.add_argument(
        '--sitemap',
        help='Path to sitemap.json or sitemap.xml (mutually exclusive with --url)'
    )
    parser.add_argument(
        '--limit',
        type=int,
        help='Maximum number of URLs to process (for testing)'
    )
    parser.add_argument(
        '--delay',
        type=float,
        default=1.0,
        help='Delay between requests in seconds (default: 1.0)'
    )
    parser.add_argument(
        '--log-file',
        help='Path to log file (optional)'
    )
    parser.add_argument(
        '--output-dir',
        default='output',
        help='Output directory (default: output)'
    )
    parser.add_argument(
        '--timeout',
        type=int,
        default=10,
        help='Request timeout in seconds (default: 10)'
    )
    parser.add_argument(
        '--retries',
        type=int,
        default=3,
        help='Number of retries for failed requests (default: 3)'
    )

    args = parser.parse_args()

    # Validate: exactly one of --url or --sitemap
    if not args.url and not args.sitemap:
        parser.error("Either --url or --sitemap is required")
    if args.url and args.sitemap:
        parser.error("Cannot use both --url and --sitemap (mutually exclusive)")

    # Check translation model
    if not has_model('de', 'en'):
        logger.error(
            "Argos DE->EN model not installed. "
            "Run: argospm install translate-de_en"
        )
        sys.exit(1)

    # Batch mode
    if args.sitemap:
        logger.info(f"Loading sitemap: {args.sitemap}")
        urls = batch.load_sitemap(args.sitemap)
        logger.info(f"Found {len(urls)} DE URLs")
        
        if args.limit:
            urls = urls[:args.limit]
            logger.info(f"Limited to first {args.limit} URLs")
        
        results = batch.run_batch(
            urls=urls,
            output_dir=args.output_dir,
            delay=args.delay,
            log_file=getattr(args, 'log_file', None)
        )
        
        sys.exit(0 if results['failed'] == 0 else 1)

    # Single-URL mode
    try:
        # Step 1: Fetch
        logger.info(f"Fetching {args.url}")
        html, meta = fetch(
            args.url,
            timeout=args.timeout,
            retries=args.retries
        )
        logger.info(
            f"Fetched {len(html)} chars from {meta['final_url']}"
        )

        # Step 2: Parse
        logger.info("Parsing HTML")
        soup, items = parse(html)
        logger.info(f"Found {len(items)} translatable items")

        # Step 3: Extract texts for translation
        texts_to_translate = []
        for item in items:
            if isinstance(item, tuple):  # (tag, attr)
                tag, attr = item
                texts_to_translate.append(tag[attr])
            else:  # NavigableString
                texts_to_translate.append(str(item))

        # Step 4: Translate
        logger.info(f"Translating {len(texts_to_translate)} items")
        translations = translate_batch(
            texts_to_translate,
            src='de',
            dst='en'
        )
        logger.info("Translation complete")

        # Step 5: Apply translations
        logger.info("Applying translations")
        apply_translations(soup, items, translations)

        # Step 6: Rewrite links
        logger.info("Rewriting /de/ -> /en/ links")
        from urllib.parse import urlparse
        domain = urlparse(meta['final_url']).netloc
        rewrite_links(soup, from_prefix='/de/', to_prefix='/en/', domain=domain)

        # Step 7: Set language
        set_lang(soup, lang='en')

        # Step 8: Save both versions
        if 'final_url' not in meta:
            logger.error("Missing final_url in fetch metadata")
            sys.exit(1)
        de_path, en_path = map_paths(meta['final_url'], args.output_dir)

        logger.info(f"Saving DE version to {de_path}")
        # Save original DE version (re-parse to get clean copy)
        de_soup, _ = parse(html)
        save_html(de_soup, de_path)

        logger.info(f"Saving EN version to {en_path}")
        save_html(soup, en_path)

        logger.info("✓ Translation complete!")
        logger.info(f"  DE: {de_path}")
        logger.info(f"  EN: {en_path}")

    except FetchError as e:
        logger.error(f"Fetch failed: {e}")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Unexpected error: {e}", exc_info=True)
        sys.exit(1)


if __name__ == '__main__':
    main()
