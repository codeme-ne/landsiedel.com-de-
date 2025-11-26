"""Environment-based settings and runtime configuration.

All settings that depend on environment variables or runtime state.
"""
import os

# Hugging Face API credentials and limits
HF_API_TOKEN = os.getenv('HF_API_TOKEN', '')
HF_API_TIMEOUT = 30.0  # seconds
HF_MAX_RETRIES = 3

# Translation backend selection (runtime configurable)
_DEFAULT_BACKEND = os.getenv('TRANSLATOR_BACKEND', 'hf').strip().lower() or 'hf'

# Caching configuration
CACHE_PATH = "translation_cache.db"
CACHE_ENABLED = True
