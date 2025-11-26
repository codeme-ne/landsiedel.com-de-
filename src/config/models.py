"""Model selection and backend logic.

Business logic for determining which translation backend and models to use.
"""
import os
from src.config.settings import _DEFAULT_BACKEND


def get_backend_name() -> str:
    """Return the configured translator backend ("hf" or "argos").

    Reads TRANSLATOR_BACKEND env var, validates, defaults to 'hf'.
    """
    backend = os.getenv('TRANSLATOR_BACKEND', _DEFAULT_BACKEND).strip().lower()
    if backend not in {'hf', 'argos'}:
        return 'hf'
    return backend


def get_model_id(src: str, dst: str) -> str:
    """Get MarianMT model ID for language pair.

    MarianMT models: Helsinki-NLP/opus-mt-{src}-{dst}
    These are smaller, translation-specific models that work on HF free tier.

    Args:
        src: Source language code (e.g., 'en')
        dst: Destination language code (e.g., 'de')

    Returns:
        Full Hugging Face model ID
    """
    return f"Helsinki-NLP/opus-mt-{src}-{dst}"
