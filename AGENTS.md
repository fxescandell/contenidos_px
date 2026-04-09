# Panxing Contenidos - Agent Guidelines

## Purpose
This is the main repository-specific instruction file for coding agents working in this project.

## Rule Files
- No `.cursor/rules/` files were found.
- No `.cursorrules` file was found.
- No `.github/copilot-instructions.md` file was found.
- This `AGENTS.md` is the primary rule file for agentic work here.

## Project Overview
Panxing Contenidos is an editorial content pipeline built with FastAPI + SQLAlchemy.
It ingests PDF, DOCX, and image files from SMB or local hotfolders, classifies them by municipality and category, builds editorial content, and exports WordPress JSON.

Municipalities: `BERGUEDA`, `CERDANYA`, `MARESME`, `GENERAL`
Categories: `AGENDA`, `NOTICIES`, `ESPORTS`, `TURISME_ACTIU`, `NENS_I_JOVES`, `CULTURA`, `GASTRONOMIA`, `CONSELLS`, `ENTREVISTES`

## Repository Map
```text
main.py                          FastAPI entry point and watcher startup
app/config/settings.py           Pydantic settings from env/.env
app/core/                        Enums, states, domain constants
app/db/                          SQLAlchemy models, session, repositories
app/api/routes/                  API and panel routes
app/services/                    Business logic and pipeline services
app/adapters/                    WordPress export adapters per category
app/templates/                   Jinja2 templates for panel/settings
tests/                           Pytest test suite
ejemplos_exportaciones/          Real JSON export examples per category
```

## Environment
- Python 3.11
- Virtualenv: `venv/`
- Dev database: `editorial.db`
- Docker dev/prod files exist
- This workspace is not a git repository

## Install and Run
Activate the environment first:

```bash
source venv/bin/activate
```

Install dependencies:

```bash
pip install -r requirements.txt -r requirements_api.txt -r requirements_remote.txt -r requirements_watcher.txt
```

Run locally:

```bash
python main.py
uvicorn main:app --reload --host 0.0.0.0 --port 8000
START_WATCHER=False uvicorn main:app --host 0.0.0.0 --port 8000
```

Docker:

```bash
cp .env.example .env
./deploy.sh dev up
cp .env.production.example .env.production
./deploy.sh prod up
```

## Test Commands
Run all tests:

```bash
python -m pytest tests/ -v
python -m pytest tests/ -v --tb=short
```

Run a single file:

```bash
python -m pytest tests/test_inbox.py -v
```

Run one test by pattern or exact node:

```bash
python -m pytest tests/test_phase2.py -v -k "test_cleaning_pipeline"
python -m pytest tests/test_phase2.py::test_cleaning_pipeline -v
```

Debugging helper:

```bash
python -m pytest tests/test_phase5.py -v --tb=short -x
```

## Lint / Validation
There is no dedicated lint config in the repository.
Use syntax validation when needed:

```bash
python -m py_compile app/services/pipeline/flow_service.py
python -m py_compile main.py app/api/routes/flows.py app/services/export/flow_export.py
```

## Architecture Notes
- Settings are DB-first with env fallback via `SettingsResolver`
- Repositories follow a generic repository pattern
- Adapters map canonical content to WordPress payloads
- Flow-based processing is the main operational path
- Remote I/O supports SMB and FTP; local mode mirrors the same concepts
- Tables are created with `Base.metadata.create_all()` at startup
- No Alembic migrations are used

## Code Style
- Comments, docstrings, and user-facing strings must be in Spanish or Catalan
- Variable names, function names, class names, and module names stay in English
- Use 4 spaces; do not use tabs
- Prefer ASCII unless accents are required for Catalan/Spanish text
- Keep changes small and focused; avoid unrelated refactors
- Do not add comments unless the logic is genuinely non-obvious
- Do not add emojis in code, docs, or commit messages unless requested

## Imports, Formatting, Types
- Order imports as: standard library, third-party, `app.*`
- Prefer absolute imports like `from app.db.models import SourceBatch`
- Avoid circular imports; use local imports only when necessary
- Preserve the style already used in the file when it is consistent
- Add type hints on function signatures and return values
- Prefer `Optional[X]` over `X | None` for consistency
- Pydantic schemas should use explicit field types and sensible defaults
- Jinja templates live in `app/templates/` and use inline CSS, not a CSS framework
- Settings and panel forms usually submit via `POST` and return `RedirectResponse`

## Naming Conventions
- Classes: `PascalCase`
- Functions and variables: `snake_case`
- Constants and enum values: `UPPER_SNAKE_CASE`
- Settings keys stay lowercase snake_case strings

## Database Rules
- Use SQLAlchemy 2 style with `Mapped[...]` and `mapped_column()`
- Primary keys are UUIDs generated with `uuid4`
- `BaseRepository.delete()` expects keyword-only `id=...`
- `SystemSetting` is in `app/db/settings_models.py`, not `app/db/models.py`
- Do not add Alembic files; startup creates the schema

## Error Handling and Logging
- For SMB/FTP/SFTP/local I/O, use `try/except Exception` and log failures
- Do not use bare `except:`
- FastAPI routes should raise `HTTPException` for client-facing errors
- Follow the logging style already present in the file
- Prefer `logging` over `print()` in newer service code unless the file consistently uses prints

## Settings Rules
- Read runtime settings with `SettingsResolver.get("key", default)`
- Call `SettingsResolver.reload(db)` before reading updated settings in endpoints
- Do not read env vars directly for runtime behavior outside bootstrap/config code
- When adding a new setting default, update `app/services/settings/service.py`

## Pipeline-Specific Rules
- Flows are independent and manually managed from the settings panel
- `active_source_mode` controls both input and output mode
- SMB and local folder mappings are stored separately
- Export JSON is batch-specific; do not accumulate old articles into new exports
- Source files should be moved to `processed/` after successful flow handling
- FTP image exports belong under the municipality folder, usually in `images/`
- Public image URLs are built from `outfolder_public_base_url`

## Testing Expectations
- Always run relevant tests after changing business logic
- At minimum, run the most specific affected test file
- If no targeted test exists, run a syntax check and explain what was validated
- Tests use `pytest` and `fastapi.testclient.TestClient`
- There is no shared `conftest.py` currently

## Known Project Notes
- `smbclient` LSP/import errors can be false positives in editors
- Existing UploadFile typing issues in `app/api/routes/settings.py` are pre-existing noise
- OCR/image processing may depend on optional runtime tools or external services
- JSON files in `ejemplos_exportaciones/` are strict structure references for category exports

## When Editing
- Prefer minimal, surgical changes
- Preserve existing behavior unless the task requires a change
- Update templates, routes, settings defaults, and services together when adding a setting
- If a category export shape changes, verify adapters, strict export examples, and settings UI together
