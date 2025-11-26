"""Translation pipeline orchestration."""
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

from src.fetcher import fetch
from src.parser import EmbeddedHtmlItem, JsonFieldItem, parse
from src.translator import TranslationContext, preview_batch, translate_batch
from src.writer import apply_translations, map_paths, rewrite_links, save_html, set_lang

logger = logging.getLogger(__name__)


def extract_texts(items: list) -> list[str]:
    """
    Extract text strings from parsed items.

    Handles:
    - (tag, attr) tuples → tag[attr]
    - JsonFieldItem → item.get_value()
    - EmbeddedHtmlItem → item.get_value()
    - NavigableString → str(item)

    Returns: List of strings ready for translation
    """
    texts = []
    for item in items:
        if isinstance(item, tuple):
            tag, attr = item
            texts.append(tag[attr])
        elif isinstance(item, JsonFieldItem):
            texts.append(item.get_value())
        elif isinstance(item, EmbeddedHtmlItem):
            texts.append(item.get_value())
        else:
            texts.append(str(item))
    return texts


@dataclass
class TranslationPipeline:
    """
    Orchestrates the fetch → parse → translate → write pipeline.

    Encapsulates HTTP settings and translation context to enable
    reusable, testable, concurrent pipelines.
    """

    timeout: int = 10
    retries: int = 3
    context: Optional[TranslationContext] = None

    def process_url(
        self,
        url: str,
        output_dir: str,
        dry_run: bool = False,
    ) -> Optional[dict]:
        """
        Process a single URL through the full translation pipeline.

        Pipeline steps:
        1. Fetch HTML
        2. Parse translatable items
        3. Extract text strings
        4. Translate DE → EN (or preview if dry_run)
        5. Apply translations
        6. Rewrite /de/ → /en/ links
        7. Set lang="en"
        8. Save DE original + EN translated

        Args:
            url: Source URL to fetch
            output_dir: Target directory for HTML files
            dry_run: If True, preview translations without calling backend or writing files

        Returns:
            None for normal processing, or dict summary for dry_run mode

        Raises:
            FetchError: For HTTP issues
            Exception: For parsing or translation errors
        """
        # Step 1: Fetch
        logger.info(f"Fetching {url}")
        html, meta = fetch(url, timeout=self.timeout, retries=self.retries)
        final_url = meta.get('final_url', url)
        logger.info(f"Fetched {len(html)} chars from {final_url}")

        # Step 2: Parse
        logger.info("Parsing HTML")
        soup, items = parse(html)
        logger.info(f"Found {len(items)} translatable items")

        # Step 3: Extract texts
        texts = extract_texts(items)

        # Step 4: Translate or preview
        if dry_run:
            plan = preview_batch(texts, src='de', dst='en')
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
                'pending_translations': len(plan.pending),
            }

        logger.info(f"Translating {len(texts)} items")
        translations = translate_batch(texts, src='de', dst='en', context=self.context)
        logger.info("Translation complete")

        # Step 5: Apply translations
        logger.info("Applying translations")
        apply_translations(soup, items, translations)

        # Step 6: Rewrite links
        logger.info("Rewriting /de/ -> /en/ links")
        domain = urlparse(final_url).netloc
        rewrite_links(soup, from_prefix='/de/', to_prefix='/en/', domain=domain)

        # Step 7: Set language
        set_lang(soup, lang='en')

        # Step 8: Save both versions
        de_path, en_path = map_paths(final_url, output_dir)

        logger.info(f"Saving DE version to {de_path}")
        Path(de_path).parent.mkdir(parents=True, exist_ok=True)
        Path(de_path).write_text(html, encoding='utf-8')

        logger.info(f"Saving EN version to {en_path}")
        save_html(soup, en_path)

        logger.info("✓ Translation complete!")
        logger.info(f"  DE: {de_path}")
        logger.info(f"  EN: {en_path}")

        return None
