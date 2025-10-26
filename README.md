# Website Translation Tool (DE → EN)

Python CLI for turning German webpages into English copies. The pipeline
fetches HTML, extracts translatable content, calls the Hugging Face Inference
API (MarianMT models), and writes both the original and translated pages to
disk. Batching, caching, and retry logic keep the number of remote calls and
latency under control.

## Key Features
- **HF backend** – uses `Helsinki-NLP/opus-mt-{src}-{dst}` translation models via
  the Hugging Face Inference API.
- **Batching + retries** – groups texts per request with exponential backoff and
  jitter (httpx + tenacity).
- **SQLite cache** – stores normalized strings in `translation_cache.db` to avoid
  re-translating shared fragments such as headers and footers.
- **Skip heuristics** – ignores punctuation-only strings, empty nodes, and text
  that already looks English when targeting `en`.
- **Whitespace-safe application** – preserves the DOM structure while inserting
  translations and adjusting `/de/` links to `/en/`.
- **Health check** – `python -m src.main --check` verifies API reachability.
  before running a full job.

## Repository Layout

```
translate/
├── src/
│   ├── fetcher.py       # HTTP fetching with retry/backoff wrappers
│   ├── parser.py        # BeautifulSoup extraction of texts and attributes
│   ├── translator.py    # HF batching, caching, skip heuristics
│   ├── hf_client.py     # httpx client with retry/backoff + error taxonomy
│   ├── cache.py         # SQLite cache implementation
│   ├── writer.py        # Apply translations & rewrite links
│   ├── batch.py         # Batch sitemap processing orchestrator
│   └── main.py          # CLI entry point
├── tests/               # pytest suite (unit + smoke integration)
├── output/              # Generated HTML (auto-detected `de_NEW` / `en_NEW`, archives under `output/archive/`)
├── translation_cache.db # Created on first run when caching enabled
└── requirements.txt
```

## Setup

1. **System deps** (for `lxml` on Debian/Ubuntu):
   ```bash
   sudo apt-get install libxml2-dev libxslt1-dev
   ```

2. **Virtual environment**:
   ```bash
   python3 -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   ```

3. **Hugging Face token**:
   - Create a free **Read** token at <https://huggingface.co/settings/tokens>
   - Either export it or create a `.env` file (loaded automatically by the CLI):
     ```bash
     export HF_API_TOKEN="hf_xxx"
     # or
     echo "HF_API_TOKEN=hf_xxx" > .env
     ```

## Usage

### Health Check

Confirm connectivity and credentials before heavier runs:

```bash
python -m src.main --check
```

Exit code 0 means the backend responded successfully; otherwise the CLI prints a
diagnostic message.

### Single URL

```bash
python -m src.main --url https://www.landsiedel.com/de/was-ist-nlp.html --output-dir output
```

Writes `output/de/...` (original) and `output/en/...` (translated) after applying
translations, rewriting `/de/` links, and setting `lang="en"`.

### Sitemap Batch

```bash
python -m src.main --sitemap sitemap.json --output-dir output --limit 5 --delay 1.0
```

- Supports JSON (`[{"url": "..."}]` or `loc` fields) and XML sitemaps.
- Deduplicates URLs and filters to `www.landsiedel.com` paths containing `/de/`.
- Produces a summary and `failed_urls.txt` if anything goes wrong.

### CLI Options (excerpt)

- `--url` / `--sitemap` – mutually exclusive entry points.
- `--limit` – cap number of sitemap entries (debugging).
- `--delay` – seconds between sitemap requests (rate limiting).
- `--timeout` / `--retries` – fetcher controls.
- `--log-file` – optional batch log file.
- `--output-dir` – root folder for generated HTML (default `output`).

### Interactive Viewer

Inspect original and translated pages in a single browser session:

```bash
python -m src.webviewer --output-dir output --open-browser
```

- Automatically selects `output/de_NEW` and `output/en_NEW` when present (falls back to `de` / `en`).
- Shows the directory tree on the left; preview uses the full width with a language toggle between EN/DE.
- Provides ready-to-send ZIP downloads for each language (also stored under `output/packages/`).
- Override with `--source-subdir` / `--target-subdir` for archival sets (now stored under `output/archive/`).
- Retries up to five consecutive ports if 8000 is busy; tweak with `--port-attempts`.
- Bind to a different host/port using `--host` / `--port` if needed.

Visit `http://127.0.0.1:8000/` (or whichever host/port you chose) to explore the files. Close the process with `Ctrl+C`.

### Publish to GitHub Pages

Generate a self-contained static viewer (under `docs/`) that GitHub Pages can host:

```bash
python -m src.static_site --output-dir output --site-dir docs
```

- Copies the current `de_NEW` / `en_NEW` trees into `docs/de` and `docs/en`.
- Emits `docs/index.html`, `docs/data/tree.json`, and ZIP downloads in `docs/packages/`.
- Push the repository with the `docs/` folder to GitHub and enable Pages (`Settings → Pages → Deploy from branch → main / docs`).
- Each time translations change, re-run the command before committing so the site stays in sync.
- Optional automation: the included GitHub Actions workflow (`.github/workflows/pages.yml`) rebuilds `docs/` and deploys to GitHub Pages on every push to `main`. Enable Pages (branch = `github-pages` deployment) after the first run.

## Testing

The test suite relies on mocked network calls; no real HTTP requests are
performed:

```bash
pytest -q
```

Targeted runs:

```bash
pytest tests/test_translator.py -v          # translator helpers + caching logic
pytest tests/test_batch.py -k sitemap       # sitemap parsing
```

## Troubleshooting

| Symptom | Likely Cause | Fix |
|---------|--------------|-----|
| `HF authentication failed` | `HF_API_TOKEN` missing or invalid | regenerate token and export / update `.env` |
| `Translation API error: 429` | Rate limit hit | wait for daily reset or lower concurrency (`--delay`) |
| Pages re-process slowly | Cache disabled or purged | ensure `translation_cache.db` exists and writable |
| CLI exits immediately | `--url`/`--sitemap` not specified | supply exactly one of the entry-point flags |

For deeper diving (response payloads, caching internals) see
[`INTEGRATION_NOTES.md`](INTEGRATION_NOTES.md).

## Operational Notes

- Caching can be cleared by deleting `translation_cache.db`.
- Translation batches respect both a maximum item count (`BATCH_SIZE`) and an
  approximate token budget (`MAX_TOKENS_PER_BATCH`) to keep requests within free
  tier limits.
- Network access is required; no offline fallback is currently implemented.
- The CLI still supports the rest of the legacy pipeline contracts so existing
  integrations can reuse `translate_batch()` and `has_model()`.
