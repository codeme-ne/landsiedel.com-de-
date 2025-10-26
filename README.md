# Website Translation Tool (DE → EN)

TDD-based Python tool for translating German websites to English using Argos Translate.

## Features

- **Fetch** HTML with retry logic and validation
- **Parse** translatable content (text, alt, title, meta)
- **Translate** using Argos Translate (offline, local)
- **Batch Processing** via sitemap.json/xml
- **Whitespace Preservation** around inline elements (links, bold, etc.)
- **Rewrite** /de/ links to /en/
- **Preserve** DOM structure
- **Save** both DE and EN versions
- **Error Handling** with detailed summary and failed_urls.txt
- **Rate Limiting** for batch processing
- **Re-serialize** HTML on save (structure preserved, attribute order may differ)

## Project Structure

```
translate/
├── src/
│   ├── __init__.py
│   ├── fetcher.py       # HTTP fetching with retries
│   ├── parser.py        # HTML parsing for translation
│   ├── translator.py    # Argos Translate wrapper
│   ├── writer.py        # Apply translations & save
│   ├── batch.py         # Batch processing (sitemap)
│   └── main.py          # CLI entry point
├── tests/
│   ├── __init__.py
│   ├── fixtures/
│   │   └── sample_de.html
│   ├── test_fetcher.py
│   ├── test_parser.py
│   ├── test_translator.py
│   ├── test_writer.py
│   ├── test_batch.py
│   └── test_integration.py
├── output/
│   ├── de/              # Original DE pages
│   └── en/              # Translated EN pages
├── requirements.txt
└── README.md
```

## Setup

### 1. Install System Dependencies (for lxml)

```bash
sudo apt-get install libxml2-dev libxslt1-dev  # Debian/Ubuntu
```

### 2. Create Virtual Environment

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 3. Install Argos Translation Model

```bash
argospm install translate-de_en
```

## Quick Start

### Single URL Translation
```bash
# Activate virtual environment
source venv/bin/activate

# Translate one page
python -m src.main --url https://www.landsiedel.com/de/was-ist-nlp.html --output-dir output
```

Output:
```
output/de/was-ist-nlp.html    # Original German
output/en/was-ist-nlp.html    # Translated English
```

### Batch Translation (Sitemap)
```bash
# Process multiple URLs from sitemap
python -m src.main --sitemap sitemap.json --output-dir output

# Limit for testing (first 5 URLs)
python -m src.main --sitemap sitemap.json --limit 5 --delay 1.0

# With log file
python -m src.main --sitemap sitemap.json --log-file batch.log
```

**Batch Output:**
```
2025-10-25 21:11:27 - INFO - Loading sitemap: sitemap.json
2025-10-25 21:11:27 - INFO - Found 101 DE URLs
2025-10-25 21:11:27 - INFO - Limited to first 3 URLs
2025-10-25 21:11:27 - INFO - Starting batch processing: 3 URLs
2025-10-25 21:11:27 - INFO - [1/3] Processing: https://www.landsiedel.com/de/page1.html
2025-10-25 21:11:41 - INFO - [1/3] Success
...
============================================================
BATCH PROCESSING COMPLETE
  Processed: 3
  Success:   3
  Failed:    0
  Skipped:   0
============================================================
```

**Output Structure:**
```
output/
├── de/
│   ├── page1.html
│   └── page2.html
└── en/
    ├── page1.html
    └── page2.html
```

**Sitemap Formats:**

JSON (custom):
```json
[
  {"url": "https://www.landsiedel.com/de/page1.html"},
  {"url": "https://www.landsiedel.com/de/page2.html"}
]
```

XML (standard sitemap.org):
```xml
<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://www.landsiedel.com/de/page1.html</loc></url>
  <url><loc>https://www.landsiedel.com/de/page2.html</loc></url>
</urlset>
```

**Batch Workflow:**
```
sitemap.json/xml
       │
       ▼
 load_sitemap()
       │
       ▼
[URL1, URL2, URL3, ...]
       │
       ▼
   run_batch()
       │
       ├─► [1/N] fetch → parse → translate → save (DE + EN)
       │        └─► delay (rate limiting)
       ├─► [2/N] fetch → parse → translate → save (DE + EN)
       │        └─► delay
       └─► [N/N] fetch → parse → translate → save (DE + EN)
                 │
                 ▼
            Summary Report
            (success/failed/skipped)
                 │
                 ▼
        failed_urls.txt (if errors)
```

## Usage

### CLI Options

**Single URL Mode:**
```bash
python -m src.main --url <URL> [OPTIONS]
```

**Batch Mode:**
```bash
python -m src.main --sitemap <PATH> [OPTIONS]
```

python -m src.main --sitemap <>

**Options:**
- `--url`: URL to translate (mutually exclusive with --sitemap)
- `--sitemap`: Path to sitemap.json or sitemap.xml (mutually exclusive with --url)
- `--limit`: Max URLs to process (for testing, batch mode only)
- `--delay`: Delay between requests in seconds (default: 1.0, batch mode only)
- `--log-file`: Path to log file (optional)
- `--output-dir`: Output directory (default: `output`)
- `--timeout`: Request timeout in seconds (default: 10)
- `--retries`: Number of retries (default: 3)

### Programmatic

```python
from src.fetcher import fetch
from src.parser import parse
from src.translator import translate_batch
from src.writer import apply_translations, rewrite_links, set_lang, save_html

# Fetch
html, meta = fetch('https://example.com/de/page')

# Parse
soup, items = parse(html)

# Extract texts
texts = [str(item).strip() for item in items if hasattr(item, 'strip')]

# Translate
translations = translate_batch(texts, src='de', dst='en')

# Apply
apply_translations(soup, items, translations)
rewrite_links(soup, from_prefix='/de/', to_prefix='/en/')
set_lang(soup, lang='en')

# Save
save_html(soup, 'output/en/page.html')
```

## Testing

Run all tests:
```bash
pytest -q
```

Run specific test file:
```bash
pytest tests/test_fetcher.py -v
pytest tests/test_batch.py -v
```

Run with coverage:
```bash
pytest --cov=src tests/
```

## Troubleshooting

### "Argos DE->EN model not installed"
```bash
# Install the translation model
argospm install translate-de_en

# Verify installation
argospm list
```

### "FetchError: Non-HTML content"
- URL liefert PDF/Image statt HTML
- Wird automatisch als "skipped" gezählt (Batch-Mode)

### Schlechte Übersetzungsqualität
Siehe [Translation Quality Improvements](#translation-quality-improvements) für Alternativen:
- **Quick Win**: DeepL Free (500K chars/Monat)
- **Best Quality**: Gemini 1.5 Flash oder Haiku 3

### Leerzeichen fehlen bei Links/Bold
Fixed in v1.1 (Whitespace Preservation).
Falls Problem weiterhin besteht:
```bash
git pull
pip install -r requirements.txt --upgrade
```

### Batch-Processing zu langsam
```bash
# Reduziere Delay (Vorsicht: Rate-Limiting!)
python -m src.main --sitemap sitemap.json --delay 0.3

# Oder limitiere URLs für Testing
python -m src.main --sitemap sitemap.json --limit 10
```

## Module Contracts

### fetcher.py
- `fetch(url, timeout, retries) → (html, meta)`
- Returns decoded HTML and metadata (final_url, encoding, content_type, status)
- Raises `FetchError` for non-HTML, 4xx/5xx after retries, or timeouts

### parser.py
- `parse(html) → (soup, items)`
- Returns BeautifulSoup object and list of translatable items
- Items: NavigableString refs + (tag, attr) tuples for alt/title/meta

### translator.py
- `has_model(src, dst) → bool`
- `translate_batch(texts, src, dst) → list[str]`
- Batch translation preserving order and empty strings

### writer.py
- `apply_translations(soup, items, translations) → None` (in-place, preserves whitespace)
- `rewrite_links(soup, from_prefix, to_prefix) → None`
- `set_lang(soup, lang) → None`
- `map_paths(url, output_dir) → (de_path, en_path)`
- `save_html(soup, path, encoding) → None`

### batch.py
- `load_sitemap_json(path) → list[str]` (deduplicated, filtered)
- `load_sitemap_xml(path) → list[str]` (namespace-safe)
- `load_sitemap(path) → list[str]` (auto-detect JSON/XML)
- `process_single_url(url, output_dir) → None` (full pipeline)
- `run_batch(urls, output_dir, delay, log_file) → dict` (orchestrator)

## Quality Gates

- ✓ All unit tests pass offline (network mocked)
- ✓ Integration test passes with Argos model (skipped if not installed)
- ✓ 41 tests pass (17 batch + 24 core)
- ✓ DOM structure preserved pre/post translation
- ✓ Whitespace preserved around inline elements (links, bold)
- ✓ No /de/ links in EN output
- ✓ `<html lang="en">` set correctly
- ✓ UTF-8 encoding for all outputs
- ✓ Batch processing: FetchError → skipped, Exception → failed
- ✓ failed_urls.txt created on errors
- ✓ Rate limiting functional (configurable delay)

## Design Principles

- **TDD**: Tests written before implementation
- **Simplicity**: Small functions, explicit error handling
- **Offline-first**: Works without external API calls
- **Fail-loud**: Explicit validation and error messages
- **No magic**: Clear naming, no hidden behavior