"""Static constants and lookup tables.

Configuration values that don't change at runtime.
"""

# Batching parameters
BATCH_SIZE = 20  # texts per API call
MAX_TOKENS_PER_BATCH = 2000  # max tokens to generate

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

# Heuristics for language detection
ENGLISH_STOPWORDS = {
    'the', 'and', 'of', 'to', 'a', 'in', 'is', 'it', 'for', 'on',
    'with', 'as', 'at', 'by', 'from', 'or', 'an', 'be', 'this', 'that'
}
