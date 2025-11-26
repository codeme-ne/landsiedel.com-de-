"""Centralized configuration for translation system.

Package structure:
- settings.py: Environment-based configuration (API tokens, cache settings)
- constants.py: Static constants (batch sizes, language maps)
- models.py: Model selection logic (get_model_id, get_backend_name)

All exports are re-exported here for backward compatibility.
"""

# Re-export environment settings
from src.config.settings import (
    HF_API_TOKEN,
    HF_API_TIMEOUT,
    HF_MAX_RETRIES,
    CACHE_PATH,
    CACHE_ENABLED,
)

# Re-export static constants
from src.config.constants import (
    BATCH_SIZE,
    MAX_TOKENS_PER_BATCH,
    TRANSLATION_TEMPERATURE,
    LANGUAGE_MAP,
    ENGLISH_STOPWORDS,
)

# Re-export model logic functions
from src.config.models import (
    get_backend_name,
    get_model_id,
)

__all__ = [
    # Settings
    'HF_API_TOKEN',
    'HF_API_TIMEOUT',
    'HF_MAX_RETRIES',
    'CACHE_PATH',
    'CACHE_ENABLED',
    # Constants
    'BATCH_SIZE',
    'MAX_TOKENS_PER_BATCH',
    'TRANSLATION_TEMPERATURE',
    'LANGUAGE_MAP',
    'ENGLISH_STOPWORDS',
    # Model logic
    'get_backend_name',
    'get_model_id',
]
