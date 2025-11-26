"""High-level translation helpers with caching and backend selection."""

from __future__ import annotations

import logging
import math
import re
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterator, Optional

from src.cache import TranslationCache
from src.config import (
    BATCH_SIZE,
    CACHE_ENABLED,
    CACHE_PATH,
    ENGLISH_STOPWORDS,
    HF_API_TIMEOUT,
    HF_MAX_RETRIES,
    LANGUAGE_MAP,
    MAX_TOKENS_PER_BATCH,
    get_backend_name,
    get_model_id,
)
from src.hf_client import AuthenticationError, HfApiError, HfClient

logger = logging.getLogger(__name__)

_MAX_LOG_SNIPPET = 80


@dataclass
class TranslationContext:
    """Encapsulates translation state to enable thread-safe, concurrent pipelines.

    This class owns the translation cache and Argos translator instances,
    eliminating global mutable state and enabling:
    - Multiple concurrent pipelines with isolated caches
    - Thread-safe operation
    - Easy testing with mock contexts
    """

    cache: Optional[TranslationCache] = None
    argos_translators: dict[tuple[str, str], Any] = field(default_factory=dict)

    @classmethod
    def create(cls, cache_enabled: bool = True, cache_path: Optional[str] = None) -> TranslationContext:
        """Create a new context with optional cache.

        Args:
            cache_enabled: Whether to enable caching (defaults to True)
            cache_path: Custom cache path (defaults to CACHE_PATH from config)

        Returns:
            New TranslationContext instance
        """
        cache = None
        if cache_enabled and CACHE_ENABLED:
            path = cache_path or CACHE_PATH
            try:
                cache = TranslationCache(path)
            except Exception as exc:  # pragma: no cover - defensive logging
                logger.warning("Failed to initialize cache: %s", exc)

        return cls(cache=cache)


# Default context for backward compatibility (lazy-initialized)
_default_context: Optional[TranslationContext] = None


def _get_default_context() -> TranslationContext:
    """Get or create the default context for backward compatibility.

    This enables existing code to work without modification while
    new code can use explicit context passing.
    """
    global _default_context
    if _default_context is None:
        _default_context = TranslationContext.create()
    return _default_context


@dataclass
class TranslationItem:
    """Represents a single text requiring translation."""

    index: int
    original: str
    normalized: str


@dataclass
class TranslationPlan:
    """Details the work required to translate a batch of texts."""

    src: str
    dst: str
    model_id: str
    cache_tag: str
    total: int
    results: list[Optional[str]]
    pending: list[TranslationItem]
    skipped_indexes: list[int]
    cache_hits: int
    candidate_count: int

    def finalize(self, originals: list[str]) -> list[str]:
        """Return a fully populated result list, using originals as fallback."""

        return [value if value is not None else originals[i] for i, value in enumerate(self.results)]


class ArgosTranslationError(Exception):
    """Raised when the Argos fallback backend cannot translate text."""


def _normalize_text(text: str) -> str:
    """Remove soft hyphens and other invisible characters."""

    return (
        text.replace("\u00AD", "")  # Soft hyphen
        .replace("\u200B", "")  # Zero-width space
        .replace("\u200C", "")  # Zero-width non-joiner
        .replace("\u200D", "")  # Zero-width joiner
    )


def _is_punctuation_only(text: str) -> bool:
    """Return True when the string contains only punctuation/separators."""

    cleaned = text.strip()
    if not cleaned:
        return True
    return all(c in "|·•\u00A0\u2022\u2023-–—\t " for c in cleaned)


def _looks_english(text: str) -> bool:
    """Heuristic: likely English if ASCII only and contains stopwords."""

    if not re.match(r"^[a-zA-Z0-9\s.,!?\'\"()-]+$", text):
        return False
    words: list[str] = []
    for raw_word in text.lower().split():
        cleaned = raw_word.strip(".,!?\'\"()-[]{}:;")
        if cleaned:
            words.append(cleaned)

    if not words:
        return False

    stopwords = [word for word in words if word in ENGLISH_STOPWORDS]
    if len(words) <= 4:
        return len(stopwords) >= 1 and (len(stopwords) / len(words)) >= 0.25

    return len(stopwords) >= 2 and (len(stopwords) / len(words)) >= 0.3


def _estimate_tokens(text: str) -> int:
    """Rough token estimate used for batching heuristics."""

    if not text:
        return 0
    stripped = text.strip()
    if not stripped:
        return 0
    return max(1, math.ceil(len(stripped) / 4))  # ~4 characters per token


def _snip(text: str, length: int = _MAX_LOG_SNIPPET) -> str:
    """Return a compact single-line snippet for logging."""

    cleaned = re.sub(r"\s+", " ", text).strip()
    if len(cleaned) <= length:
        return cleaned
    return cleaned[: length - 3] + "..."


def _build_translation_plan(
    texts: list[str],
    src: str,
    dst: str,
    *,
    backend: str = "hf",
    use_cache: bool = True,
    context: Optional[TranslationContext] = None,
) -> TranslationPlan:
    """Prepare translation work by applying skips and cache lookups.

    Args:
        texts: List of texts to translate
        src: Source language code
        dst: Destination language code
        backend: Translation backend to use
        use_cache: Whether to use cache
        context: Translation context (uses default if None)
    """
    if context is None:
        context = _get_default_context()

    total = len(texts)
    results: list[Optional[str]] = list(texts)
    pending: list[TranslationItem] = []
    skipped: list[int] = []

    for index, text in enumerate(texts):
        if not text or not text.strip():
            skipped.append(index)
            continue
        if _is_punctuation_only(text):
            skipped.append(index)
            continue
        if dst == "en" and _looks_english(text):
            skipped.append(index)
            continue

        normalized = _normalize_text(text)
        pending.append(TranslationItem(index=index, original=text, normalized=normalized))
        results[index] = None

    candidate_count = len(pending)
    cache_hits = 0
    model_id = get_model_id(src, dst)
    cache_tag = f"{backend}:{model_id}" if backend != "hf" else model_id

    if not pending:
        return TranslationPlan(
            src=src,
            dst=dst,
            model_id=model_id,
            cache_tag=cache_tag,
            total=total,
            results=results,
            pending=pending,
            skipped_indexes=skipped,
            cache_hits=cache_hits,
            candidate_count=candidate_count,
        )

    cache = context.cache if (use_cache and backend != "argos") else None
    if cache:
        cache_keys = [item.normalized for item in pending]
        cached = cache.get_many(cache_keys, src, dst, cache_tag)
        remaining: list[TranslationItem] = []

        for item in pending:
            cached_value = cached.get(item.normalized)
            if cached_value:
                results[item.index] = cached_value
                cache_hits += 1
            else:
                remaining.append(item)

        pending = remaining

    return TranslationPlan(
        src=src,
        dst=dst,
        model_id=model_id,
        cache_tag=cache_tag,
        total=total,
        results=results,
        pending=pending,
        skipped_indexes=skipped,
        cache_hits=cache_hits,
        candidate_count=candidate_count,
    )


def preview_batch(
    texts: list[str],
    src: str = "de",
    dst: str = "en",
    *,
    context: Optional[TranslationContext] = None,
) -> TranslationPlan:
    """Return a translation plan without performing any API calls.

    Args:
        texts: List of texts to preview
        src: Source language code
        dst: Destination language code
        context: Translation context (uses default if None)
    """
    backend = get_backend_name()
    return _build_translation_plan(texts, src, dst, backend=backend, use_cache=True, context=context)


def _log_plan_summary(plan: TranslationPlan, backend: str, dry_run: bool) -> None:
    """Emit useful summary lines for diagnostics."""

    mode = "preview" if dry_run else "translation"
    logger.info(
        "Starting %s: %d texts (%s -> %s) via %s backend",
        mode,
        plan.total,
        plan.src,
        plan.dst,
        backend.upper(),
    )

    if plan.candidate_count == 0:
        logger.info("No texts require translation (all skipped)")
        return

    logger.info("After filtering: %d/%d texts need translation", plan.candidate_count, plan.total)
    if plan.cache_hits:
        logger.info("Cache hits: %d/%d", plan.cache_hits, plan.candidate_count)
    logger.info("After cache: %d misses remain", len(plan.pending))


def translate_batch(
    texts: list[str],
    src: str = "de",
    dst: str = "en",
    *,
    dry_run: bool = False,
    context: Optional[TranslationContext] = None,
) -> list[str]:
    """Translate a list of strings while preserving order and applying caching.

    Args:
        texts: List of texts to translate
        src: Source language code
        dst: Destination language code
        dry_run: If True, only preview without actual translation
        context: Translation context (uses default if None)
    """
    if context is None:
        context = _get_default_context()

    if not texts:
        return []

    backend = get_backend_name()
    plan = _build_translation_plan(texts, src, dst, backend=backend, use_cache=not dry_run, context=context)
    _log_plan_summary(plan, backend, dry_run)

    if dry_run:
        _log_dry_run(plan, backend)
        return list(texts)

    if plan.candidate_count == 0:
        return plan.finalize(texts)

    if len(plan.pending) == 0:
        logger.info("All translations served from cache!")
        return plan.finalize(texts)

    if not has_model(src, dst, context=context):
        if backend == "argos":
            raise RuntimeError(
                f"Argos translation backend unavailable for {src}->{dst}. "
                "Install the appropriate language package or set TRANSLATOR_BACKEND=hf."
            )
        raise RuntimeError(
            f"Translation not available for {src}->{dst}. "
            "Ensure HF_API_TOKEN is set and reachable."
        )

    new_translations: dict[str, str] = {}
    pending_items = plan.pending

    try:
        with _translation_callable(backend, src, dst, context) as translate_fn:
            batch_number = 0
            cursor = 0
            total_items = len(pending_items)

            while cursor < total_items:
                batch_items: list[TranslationItem] = []
                token_total = 0

                while cursor < total_items and len(batch_items) < BATCH_SIZE:
                    item = pending_items[cursor]
                    estimated = _estimate_tokens(item.normalized)

                    if (
                        batch_items
                        and MAX_TOKENS_PER_BATCH
                        and token_total + estimated > MAX_TOKENS_PER_BATCH
                    ):
                        break

                    batch_items.append(item)
                    token_total += estimated
                    cursor += 1

                batch_number += 1
                batch_texts = [item.normalized for item in batch_items]

                logger.info(
                    "Translating batch %d (%d texts, ~%d tokens)",
                    batch_number,
                    len(batch_texts),
                    token_total,
                )

                translations = translate_fn(batch_texts)

                if len(translations) != len(batch_items):
                    logger.warning(
                        "Translation count mismatch in batch %d: expected %d, got %d",
                        batch_number,
                        len(batch_items),
                        len(translations),
                    )

                for item, translation in zip(batch_items, translations):
                    plan.results[item.index] = translation
                    new_translations[item.normalized] = translation

                if len(translations) < len(batch_items):
                    for item in batch_items[len(translations) :]:
                        if plan.results[item.index] is None:
                            plan.results[item.index] = item.original

    except AuthenticationError as exc:
        logger.error("Authentication error during translation: %s", exc)
        for item in pending_items:
            if plan.results[item.index] is None:
                plan.results[item.index] = item.original
        raise RuntimeError("HF authentication failed. Check HF_API_TOKEN.") from exc
    except HfApiError as exc:
        logger.error("Translation failed: %s", exc)
        for item in pending_items:
            if plan.results[item.index] is None:
                plan.results[item.index] = item.original
        raise RuntimeError(f"Translation API error: {exc}") from exc
    except ArgosTranslationError as exc:
        logger.error("Argos translation failed: %s", exc)
        for item in pending_items:
            if plan.results[item.index] is None:
                plan.results[item.index] = item.original
        raise RuntimeError(str(exc)) from exc
    except Exception as exc:  # pragma: no cover - defensive logging
        logger.error("Unexpected translation failure: %s", exc)
        for item in pending_items:
            if plan.results[item.index] is None:
                plan.results[item.index] = item.original
        raise

    if context.cache and new_translations:
        try:
            context.cache.set_many(new_translations, src, dst, plan.cache_tag)
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.warning("Failed to update cache: %s", exc)

    logger.info("Translation complete: %d texts processed", plan.total)
    return plan.finalize(texts)


def _log_dry_run(plan: TranslationPlan, backend: str) -> None:
    """Emit detailed information for dry-run planning."""

    logger.info(
        "Dry run: %d/%d texts would be translated via %s backend (cache hits: %d)",
        len(plan.pending),
        plan.total,
        backend.upper(),
        plan.cache_hits,
    )
    for item in plan.pending:
        logger.info("  - idx %d: %s", item.index, _snip(item.original))


@contextmanager
def _translation_callable(
    backend: str,
    src: str,
    dst: str,
    context: TranslationContext,
) -> Iterator[Callable[[list[str]], list[str]]]:
    """Yield a callable that performs translations for the selected backend.

    Args:
        backend: Translation backend to use
        src: Source language code
        dst: Destination language code
        context: Translation context for Argos translators
    """
    if backend == "hf":
        with HfClient(timeout=HF_API_TIMEOUT, max_retries=HF_MAX_RETRIES) as client:
            yield lambda texts: client.translate_texts(texts, src=src, dst=dst)
    elif backend == "argos":
        yield lambda texts: _argos_translate_texts(texts, src, dst, context)
    else:  # pragma: no cover - configuration guard
        raise ValueError(f"Unsupported translation backend: {backend}")


def _argos_translate_texts(texts: list[str], src: str, dst: str, context: TranslationContext) -> list[str]:
    """Translate texts using the Argos Translate fallback backend.

    Args:
        texts: List of texts to translate
        src: Source language code
        dst: Destination language code
        context: Translation context containing Argos translators cache
    """
    translator = _load_argos_translator(src, dst, context)
    if translator is None:
        raise ArgosTranslationError(
            f"Argos translator for {src}->{dst} not installed. Install it via "
            f"`argospm install translate-{src}_{dst}`."
        )

    translations: list[str] = []
    for text in texts:
        try:
            translations.append(translator.translate(text))
        except Exception as exc:
            raise ArgosTranslationError(f"Argos translation failed: {exc}") from exc
    return translations


def _get_argos_attr(obj: object, attr_name: str):
    """Get attribute from Argos object, handling callable getters."""
    value = getattr(obj, attr_name, None)
    if value is None:
        return None
    if callable(value):
        try:
            return value()
        except TypeError:
            pass  # Some versions expose attributes directly
    return value


def _resolve_argos_lang_code(value: object) -> Optional[str]:
    """Extract language code from Argos language object."""
    if value is None:
        return None
    code = _get_argos_attr(value, "code")
    return code if isinstance(code, str) else (value if isinstance(value, str) else None)


def _find_argos_translator(languages: list, src: str, dst: str) -> Optional[object]:
    """Search installed Argos languages for matching translator."""
    for language in languages:
        lang_code = _get_argos_attr(language, "code")
        if lang_code != src:
            continue

        # Check all possible translation collection attributes
        translation_attrs = ("translations", "translations_from", "translations_to")
        candidates = [_get_argos_attr(language, attr) for attr in translation_attrs]

        for collection in filter(None, candidates):
            for candidate in filter(None, collection):
                # Try multiple attribute names for source/target codes
                source_code = (
                    _resolve_argos_lang_code(_get_argos_attr(candidate, "from_lang"))
                    or _resolve_argos_lang_code(_get_argos_attr(candidate, "from_code"))
                    or lang_code
                )
                if source_code != src:
                    continue

                target_code = (
                    _resolve_argos_lang_code(_get_argos_attr(candidate, "to_lang"))
                    or _resolve_argos_lang_code(_get_argos_attr(candidate, "to_code"))
                )
                if target_code == dst:
                    return candidate
    return None


def _load_argos_translator(src: str, dst: str, context: TranslationContext) -> Optional[object]:
    """Load (and cache) an Argos translator for the given language pair.

    Args:
        src: Source language code
        dst: Destination language code
        context: Translation context containing Argos translators cache
    """
    key = (src, dst)
    if key in context.argos_translators:
        return context.argos_translators[key]

    try:
        from argostranslate import translate as argos_translate
    except ImportError:
        logger.warning(
            "TRANSLATOR_BACKEND=argos but argostranslate is not installed. "
            "Run `pip install argostranslate argostranslate-models` to enable the fallback."
        )
        context.argos_translators[key] = None
        return None

    try:
        languages = argos_translate.load_installed_languages()
    except Exception as exc:
        logger.error("Failed to load Argos languages: %s", exc)
        context.argos_translators[key] = None
        return None

    translator = _find_argos_translator(languages, src, dst)

    if translator is None:
        logger.warning(
            "Argos fallback missing language pair %s -> %s. "
            "Install it via `argospm install translate-%s_%s`.",
            src,
            dst,
            src,
            dst,
        )

    context.argos_translators[key] = translator
    return translator


def _argos_has_model(src: str, dst: str, context: Optional[TranslationContext] = None) -> bool:
    """Return True when the Argos backend can handle the language pair.

    Args:
        src: Source language code
        dst: Destination language code
        context: Translation context (uses default if None)
    """
    if context is None:
        context = _get_default_context()
    return _load_argos_translator(src, dst, context) is not None


def has_model(src: str = "de", dst: str = "en", *, context: Optional[TranslationContext] = None) -> bool:
    """Check if translation is available for the configured backend.

    Args:
        src: Source language code
        dst: Destination language code
        context: Translation context (uses default if None)
    """
    if src not in LANGUAGE_MAP or dst not in LANGUAGE_MAP:
        logger.warning("Unsupported language pair: %s -> %s", src, dst)
        return False

    backend = get_backend_name()
    if backend == "argos":
        return _argos_has_model(src, dst, context)

    try:
        with HfClient(timeout=HF_API_TIMEOUT, max_retries=HF_MAX_RETRIES) as client:
            return client.health_check(src, dst)
    except AuthenticationError:
        return False
    except HfApiError as exc:
        logger.warning("Health check failed: %s", exc)
        return False


__all__ = [
    "TranslationContext",
    "has_model",
    "preview_batch",
    "translate_batch",
    "_is_punctuation_only",
    "_looks_english",
    "_normalize_text",
]
