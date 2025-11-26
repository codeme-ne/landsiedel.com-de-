#!/usr/bin/env python3
"""CLI for website translation pipeline"""
import argparse
import logging
import sys
from pathlib import Path

# Load environment variables (for HF_API_TOKEN)
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from src.fetcher import FetchError
from src.translator import has_model
from src.pipeline import TranslationPipeline
from src import batch

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

# Suppress noisy library loggers and prevent token leakage
logging.getLogger('urllib3').setLevel(logging.WARNING)
logging.getLogger('requests').setLevel(logging.WARNING)
logging.getLogger('httpx').setLevel(logging.ERROR)

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
    parser.add_argument(
        '--check',
        action='store_true',
        help='Only run the Hugging Face translation health check and exit'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Plan translations without calling the backend or writing files'
    )

    args = parser.parse_args()

    # Health check mode takes precedence
    if args.check:
        if args.dry_run:
            parser.error("--check cannot be combined with --dry-run")
        if args.url or args.sitemap:
            parser.error("--check cannot be combined with --url or --sitemap")
        if has_model('de', 'en'):
            logger.info("Hugging Face translation backend is reachable.")
            sys.exit(0)
        logger.error(
            "Hugging Face translation backend unavailable. "
            "Ensure HF_API_TOKEN is set and network access is available."
        )
        sys.exit(1)

    # Validate: exactly one of --url or --sitemap
    if not args.url and not args.sitemap:
        parser.error("Either --url or --sitemap is required")
    if args.url and args.sitemap:
        parser.error("Cannot use both --url and --sitemap (mutually exclusive)")

    # Check translation API access
    if not args.dry_run and not has_model('de', 'en'):
        logger.error(
            "Hugging Face translation backend unavailable. "
            "Set HF_API_TOKEN and verify connectivity with --check."
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
            log_file=getattr(args, 'log_file', None),
            dry_run=args.dry_run
        )

        sys.exit(0 if results['failed'] == 0 else 1)

    # Single-URL mode
    try:
        pipeline = TranslationPipeline(
            timeout=args.timeout,
            retries=args.retries
        )
        result = pipeline.process_url(
            args.url,
            args.output_dir,
            dry_run=args.dry_run
        )

        if args.dry_run:
            logger.info("Dry run complete (no files written)")

        sys.exit(0)

    except FetchError as e:
        logger.error(f"Fetch failed: {e}")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Unexpected error: {e}", exc_info=True)
        sys.exit(1)


if __name__ == '__main__':
    main()
