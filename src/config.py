"""Centralized configuration for translation system.

All configurable parameters in one place for easy management.
"""
import os

# Hugging Face API
HF_API_TOKEN = os.getenv('HF_API_TOKEN', '')
HF_API_TIMEOUT = 30.0  # seconds
HF_MAX_RETRIES = 3

# Translation backend selection
_DEFAULT_BACKEND = os.getenv('TRANSLATOR_BACKEND', 'hf').strip().lower() or 'hf'


def get_backend_name() -> str:
    """Return the configured translator backend ("hf" or "argos")."""
    backend = os.getenv('TRANSLATOR_BACKEND', _DEFAULT_BACKEND).strip().lower()
    if backend not in {'hf', 'argos'}:
        return 'hf'
    return backend

def get_model_id(src: str, dst: str) -> str:
    """Get MarianMT model ID for language pair.

    MarianMT models: Helsinki-NLP/opus-mt-{src}-{dst}
    These are smaller, translation-specific models that work on HF free tier.
    """
    return f"Helsinki-NLP/opus-mt-{src}-{dst}"

# Batching
BATCH_SIZE = 20  # texts per API call
MAX_TOKENS_PER_BATCH = 2000  # max tokens to generate

# Caching
CACHE_PATH = "translation_cache.db"
CACHE_ENABLED = True

# Translation parameters
TRANSLATION_TEMPERATURE = 0.3  # Lower = more deterministic

# Language mapping (ISO 639-1 code → full name)
LANGUAGE_MAP = {
    'en': 'English',
    'de': 'German',
    'fr': 'French',
    'es': 'Spanish',
    'ru': 'Russian',
    'hi': 'Hindi',
    'zh': 'Chinese',
    'pt': 'Portuguese',
    'it': 'Italian',
    'ja': 'Japanese',
    'ko': 'Korean',
    'ar': 'Arabic'
}

# Heuristics
ENGLISH_STOPWORDS = {
    'the', 'and', 'of', 'to', 'a', 'in', 'is', 'it', 'for', 'on',
    'with', 'as', 'at', 'by', 'from', 'or', 'an', 'be', 'this', 'that'
}
