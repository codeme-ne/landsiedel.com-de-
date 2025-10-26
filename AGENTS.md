# Repository Guidelines

## Project Structure & Module Organization
- Source code lives in `src/`: `fetcher.py`, `parser.py`, `translator.py`, `writer.py`, `main.py` (CLI).
- Tests are in `tests/` with unit tests and `tests/fixtures/` for sample inputs.
- Outputs are written to `output/de/` (original) and `output/en/` (translated).
- Optional inputs: `sitemap.json` / `sitemap.xml` may list URLs to process.

## Build, Test, and Development Commands
- Create env and install deps:
  `python3 -m venv venv && source venv/bin/activate && pip install -r requirements.txt`
- Install translation model (required for full integration):
  `argospm install translate-de_en`
- Run locally (CLI):
  `python -m src.main --url https://example.com/de/page --output-dir output`
- Run tests (unit + integration):
  `pytest -q`
- Focused tests:
  `pytest tests/test_parser.py -v` or `pytest -k translator -q`
- Optional coverage (if plugin installed):
  `pytest --cov=src tests/`

## Coding Style & Naming Conventions
- Follow PEP 8 with 4-space indentation and UTF-8 encoding.
- Naming: modules/functions `lower_snake_case`, classes `PascalCase`, constants `UPPER_SNAKE_CASE`.
- Prefer small, pure functions; explicit errors; no hidden global state.
- Add type hints where practical and docstrings for public functions.
- Avoid hardcoded paths; pass directories/URLs via parameters or CLI flags.

## Testing Guidelines
- Framework: pytest. Tests live in `tests/` and use `test_*.py` naming.
- Unit tests mock network; do not perform real HTTP calls.
- `test_integration.py` exercises the full flow and auto-skips if the Hugging Face backend is unavailable.
- Add tests for new behavior and regressions; keep fixtures in `tests/fixtures/`.

## Commit & Pull Request Guidelines
- Use Conventional Commits: `feat:`, `fix:`, `docs:`, `test:`, `refactor:`; imperative mood, concise subject (~50 chars).
- Include scope when helpful: e.g., `feat(parser): handle meta descriptions`.
- PRs should include: clear description, linked issues, before/after examples (paths under `output/`), and tests for changes.
- Ensure `pytest -q` passes locally before opening/merging a PR.

## Security & Configuration Tips
- Keep the tool offline-first; avoid introducing external services.
- Do not commit secrets or environment-specific paths.
- Use CLI options (`--timeout`, `--retries`, `--output-dir`) instead of globals for configuration.
