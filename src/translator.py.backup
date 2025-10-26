"""Translation wrapper for Argos Translate"""
import logging
import re

try:
    import argostranslate.translate
except ImportError:
    argostranslate = None

logger = logging.getLogger(__name__)

# Common English stopwords for heuristic
ENGLISH_STOPWORDS = {
    'the', 'and', 'of', 'to', 'a', 'in', 'is', 'it', 'for', 'on',
    'with', 'as', 'at', 'by', 'from', 'or', 'an', 'be', 'this', 'that'
}


def _normalize_text(text: str) -> str:
    """Remove soft hyphens and other invisible characters"""
    return (text
            .replace('\u00AD', '')      # Soft hyphen
            .replace('\u200B', '')      # Zero-width space
            .replace('\u200C', '')      # Zero-width non-joiner
            .replace('\u200D', ''))     # Zero-width joiner


def _is_punctuation_only(text: str) -> bool:
    """Check if string contains only punctuation/separators"""
    # Strip whitespace and check if only contains separator chars
    cleaned = text.strip()
    if not cleaned:
        return True
    # Check if all chars are punctuation or whitespace
    return all(c in '|·•\u00A0\u2022\u2023-–—\t ' for c in cleaned)


def _looks_english(text: str) -> bool:
    """
    Simple heuristic: likely English if only ASCII letters
    and contains common English stopwords.
    """
    # Must contain only ASCII letters, digits, and common punctuation
    if not re.match(r'^[a-zA-Z0-9\s.,!?\'"()-]+$', text):
        return False

    # Check for English stopwords
    words = text.lower().split()
    return any(word in ENGLISH_STOPWORDS for word in words)


def has_model(src: str = 'de', dst: str = 'en') -> bool:
    """
    Check if translation model is installed.

    Returns False if argostranslate not available.
    """
    if argostranslate is None:
        logger.warning("argostranslate not installed")
        return False

    langs = argostranslate.translate.get_installed_languages()
    src_lang = next((l for l in langs if l.code == src), None)
    dst_lang = next((l for l in langs if l.code == dst), None)

    if not src_lang or not dst_lang:
        return False

    translation = src_lang.get_translation(dst_lang)
    return translation is not None


def translate_batch(texts: list[str], src: str = 'de', dst: str = 'en') -> list[str]:
    """
    Translate list of strings, preserving order.

    Skips:
    - Empty/whitespace-only strings
    - Punctuation-only separators
    - Text that looks like English (ASCII + stopwords)

    Normalizes:
    - Removes soft hyphens before translation
    """
    if argostranslate is None:
        raise RuntimeError(
            "argostranslate not installed - cannot translate"
        )

    # Get translation object
    langs = argostranslate.translate.get_installed_languages()
    src_lang = next((l for l in langs if l.code == src), None)
    dst_lang = next((l for l in langs if l.code == dst), None)

    if not src_lang or not dst_lang:
        raise RuntimeError(
            f"Language pair {src}->{dst} not installed"
        )

    translation = src_lang.get_translation(dst_lang)
    if not translation:
        raise RuntimeError(
            f"No translation available for {src}->{dst}"
        )

    # Translate with skip logic
    results = []
    for text in texts:
        # Skip empty/whitespace
        if not text or not text.strip():
            results.append(text)
        # Skip punctuation-only separators
        elif _is_punctuation_only(text):
            results.append(text)
        # Skip likely English text
        elif _looks_english(text):
            results.append(text)
        else:
            # Normalize and translate
            normalized = _normalize_text(text)
            translated = translation.translate(normalized)
            results.append(translated)

    return results
