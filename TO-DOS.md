# TO-DOS

## High Priority Performance Fixes - 2025-11-26 05:42

- **Add HTTP connection pooling** - Reuse connections instead of creating new one per request. **Problem:** Each request creates new TCP connection, wasting 50-200ms per URL in handshake overhead. At 1000 URLs this wastes 50-200 seconds. **Files:** `src/fetcher.py:35`. **Solution:** Switch to httpx.Client() with session reuse, or create requests.Session() once and reuse.

- **Implement concurrent URL processing** - Process multiple URLs in parallel with rate limiting. **Problem:** URLs processed serially with 1s sleep between each. 100 URLs = 100+ seconds wasted on sleeps alone. **Files:** `src/batch.py:285-286`. **Solution:** Use ThreadPoolExecutor with 5-10 workers and token bucket rate limiter.

- **Remove double HTML parsing** - Save original HTML directly instead of re-parsing. **Problem:** Same HTML parsed twice - once for translation, again just to save DE version. Wastes 10-50ms per page. **Files:** `src/batch.py:201-202`. **Solution:** Either save original HTML string directly, or use copy.deepcopy(soup) before translation.

## Architecture Improvements - 2025-11-26 05:42

- **Eliminate global mutable state in translator** - Convert to dependency injection pattern. **Problem:** Global _cache and _ARGOS_TRANSLATORS singletons cause thread safety issues, testing difficulties, and prevent concurrent pipelines with different configs. **Files:** `src/translator.py:31,34,73-94`. **Solution:** Create TranslationPipeline class that owns cache instance, pass dependencies explicitly.

- **Refactor main.py god object** - Extract pipeline logic to reusable class. **Problem:** main() function is 206 lines with mixed concerns (CLI parsing, validation, orchestration, error handling). Duplicates logic from batch.py. **Files:** `src/main.py:37-242`, `src/batch.py:148-159`. **Solution:** Create src/pipeline.py with TranslationPipeline class, extract shared text extraction to parser module.

- **Split config.py responsibilities** - Separate settings, constants, and model selection. **Problem:** config.py mixes environment access, business logic (get_model_id), and static constants. Cannot swap config sources or validate at startup. **Files:** `src/config.py:1-63`. **Solution:** Create src/config/ package with settings.py (Pydantic), constants.py, and models.py.

## Code Quality Improvements - 2025-11-26 05:42

- **Extract duplicate HTML template** - Consolidate 400+ lines of duplicate HTML. **Problem:** webviewer.py and static_site.py contain nearly identical embedded HTML with minor differences. **Files:** `src/webviewer.py:518-925`, `src/static_site.py:134-513`. **Solution:** Extract to templates/viewer.html, use string substitution for differences.

- **Refactor Argos translator loader** - Simplify 100-line compatibility function. **Problem:** _load_argos_translator() handles multiple Argos API versions with reflection, 4 levels of nesting, hard to test/maintain. **Files:** `src/translator.py:448-548`. **Solution:** Extract version detection, create adapter classes per version, or drop support for old versions.

- **Add SQLite connection pooling** - Maintain persistent connection instead of open/close per query. **Problem:** New SQLite connection opened for every cache operation, adding 1-5ms overhead per query. **Files:** `src/cache.py:36-45`. **Solution:** Store connection in instance variable, add close() method and context manager support.
