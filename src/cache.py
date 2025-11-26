"""Persistent SQLite cache for translations.

Caches translations to avoid redundant API calls.
Cache key is based on text content, languages, and model.
"""
import hashlib
import logging
import sqlite3
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class TranslationCache:
    """SQLite-backed translation cache.

    Features:
    - SHA256-based cache keys (text + languages + model)
    - Batch get/set operations for efficiency
    - Automatic table creation
    - Persistent connection with multi-threaded access
    """

    def __init__(self, cache_path: str = "translation_cache.db"):
        """Initialize cache.

        Args:
            cache_path: Path to SQLite database file
        """
        self.cache_path = Path(cache_path)
        self._conn: Optional[sqlite3.Connection] = None
        self._ensure_table()

    @property
    def conn(self) -> sqlite3.Connection:
        """Get or create the database connection.

        Returns:
            Persistent SQLite connection with timeout and busy handling
        """
        if self._conn is None:
            self._conn = sqlite3.connect(
                str(self.cache_path),
                check_same_thread=False,  # Allow multi-threaded access
                timeout=5.0  # Prevent indefinite hangs
            )
            self._conn.execute("PRAGMA busy_timeout = 5000")
        return self._conn

    def close(self):
        """Close the database connection."""
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def __enter__(self):
        """Context manager entry."""
        return self

    def __exit__(self, *args):
        """Context manager exit - ensures connection cleanup."""
        self.close()

    def __del__(self):
        """Cleanup connection on garbage collection."""
        self.close()

    def _ensure_table(self):
        """Create cache table if it doesn't exist"""
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS translations (
                cache_key TEXT PRIMARY KEY,
                translation TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        # Index on cache_key for fast lookups (implicit via PRIMARY KEY)
        self.conn.commit()

    def _make_key(
        self,
        text: str,
        src: str,
        dst: str,
        model: str = "Qwen/Qwen2.5-7B-Instruct"
    ) -> str:
        """Generate cache key from text and parameters.

        Args:
            text: Text to translate
            src: Source language code
            dst: Destination language code
            model: Model identifier

        Returns:
            SHA256 hex digest
        """
        # Normalize text: strip whitespace, lowercase for caching
        normalized = text.strip()
        key_string = f"{normalized}|{src}|{dst}|{model}"
        return hashlib.sha256(key_string.encode('utf-8')).hexdigest()

    def get_many(
        self,
        texts: list[str],
        src: str,
        dst: str,
        model: str = "Qwen/Qwen2.5-7B-Instruct"
    ) -> dict[str, Optional[str]]:
        """Retrieve multiple translations from cache.

        Args:
            texts: List of texts to look up
            src: Source language code
            dst: Destination language code
            model: Model identifier

        Returns:
            Dict mapping text -> translation (None if not cached)
        """
        if not texts:
            return {}

        # Generate cache keys
        key_map = {text: self._make_key(text, src, dst, model) for text in texts}
        cache_keys = list(key_map.values())

        # Query database
        results = {}
        # Use parameterized query with placeholders
        placeholders = ','.join('?' * len(cache_keys))
        query = f"""
            SELECT cache_key, translation
            FROM translations
            WHERE cache_key IN ({placeholders})
        """
        cursor = self.conn.execute(query, cache_keys)

        # Build reverse lookup: cache_key -> translation
        key_to_translation = {row[0]: row[1] for row in cursor}

        # Map back to original texts
        for text, cache_key in key_map.items():
            results[text] = key_to_translation.get(cache_key)

        # Log cache hit rate
        hits = sum(1 for v in results.values() if v is not None)
        logger.info(f"Cache: {hits}/{len(texts)} hits ({hits*100//len(texts) if texts else 0}%)")

        return results

    def set_many(
        self,
        data: dict[str, str],
        src: str,
        dst: str,
        model: str = "Qwen/Qwen2.5-7B-Instruct"
    ):
        """Store multiple translations in cache.

        Args:
            data: Dict mapping original text -> translation
            src: Source language code
            dst: Destination language code
            model: Model identifier
        """
        if not data:
            return

        # Prepare batch insert
        rows = [
            (self._make_key(text, src, dst, model), translation)
            for text, translation in data.items()
        ]

        # Use REPLACE to update existing entries
        self.conn.executemany(
            "REPLACE INTO translations (cache_key, translation) VALUES (?, ?)",
            rows
        )
        self.conn.commit()

        logger.info(f"Cached {len(rows)} new translations")

    def clear(self):
        """Clear all cached translations"""
        self.conn.execute("DELETE FROM translations")
        self.conn.commit()
        logger.info("Cache cleared")

    def stats(self) -> dict:
        """Get cache statistics.

        Returns:
            Dict with cache stats (size, oldest, newest)
        """
        cursor = self.conn.execute("""
            SELECT
                COUNT(*) as total,
                MIN(created_at) as oldest,
                MAX(created_at) as newest
            FROM translations
        """)
        row = cursor.fetchone()

        return {
            "total_entries": row[0],
            "oldest": row[1],
            "newest": row[2]
        }
