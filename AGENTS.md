# Panxing Contenidos - Agent Guidelines

## Project Overview

Editorial content pipeline (FastAPI + SQLAlchemy). Ingests documents (PDF/DOCX/images) from SMB/FTP/local hotfolders, classifies them by municipality (Bergueda, Cerdanya, Maresme) and category (Agenda, Noticies, Esports, etc.), and exports to WordPress JSON format. Spanish/Catalan language for all comments, docstrings, and user-facing strings.

## Commands

```bash
# Activate environment
source venv/bin/activate

# Install all dependencies
pip install -r requirements.txt -r requirements_api.txt -r requirements_remote.txt -r requirements_watcher.txt

# Run the application
python main.py
# or with hot reload:
uvicorn main:app --reload --host 0.0.0.0 --port 8000

# Run all tests
python -m pytest tests/ -v

# Run a single test file
python -m pytest tests/test_inbox.py -v

# Run a single test by name
python -m pytest tests/test_phase2.py -v -k "test_cleaning_pipeline"

# Run tests with output
python -m pytest tests/ -v --tb=short 2>&1 | head -80
```

## Architecture

```
main.py                     # FastAPI entry point, mounts routers, starts WatcherService
app/
  config/settings.py         # Pydantic BaseSettings, loads .env
  core/                     # Domain enums (states, categories, municipalities)
  db/                       # SQLAlchemy 2.0 models, session, repositories
  services/                 # Business logic (pipeline stages)
    pipeline/orchestrator   # Main pipeline coordinator
    remote/clients.py       # SMB/FTP/SFTP/Local clients
    inbox/                  # Inbox abstraction (factory + polling)
    settings/               # SettingsService + SettingsResolver (DB + env + cache)
  api/routes/               # FastAPI routers (api_v1, panel, settings, inbox)
  adapters/                 # WordPress CPT-specific field mappers
  templates/settings/       # Jinja2 HTML for settings UI
tests/                      # pytest tests (test_base, test_phase2-5, test_inbox)
```

**Key patterns:** Abstract base classes per service, factory pattern for adapters and inbox clients, repository pattern with generics, module-level singletons. Settings use a hybrid DB-first / env-fallback / in-memory cache approach (`SettingsResolver`).

## Code Style

- **Language:** All comments, docstrings, and user-facing strings in Spanish/Catalan. Variable/method names in English.
- **Indentation:** 4 spaces. No tabs.
- **Imports:** stdlib, then third-party, then `app.*`. Use absolute imports: `from app.db.models import SourceBatch`.
- **Type hints:** Use on function signatures and return types. Prefer `Optional[X]` over `X | None` for consistency.
- **Naming:** `PascalCase` classes, `snake_case` functions/variables, `UPPER_SNAKE_CASE` enum values and constants.
- **SQLAlchemy:** Use `mapped_column()` with `Mapped[type]` annotations. All PKs are UUID (`uuid4`).
- **No comments unless explicitly asked.** Do not add explanatory comments to code.
- **No emojis** in code or commit messages unless user explicitly requests them.
- **Docstrings:** Spanish, triple-quoted, on key functions only. Keep concise.
- **Error handling:** Use `try/except Exception` for remote I/O (SMB, FTP, SFTP). Log errors. Do not use bare `except:`. FastAPI routes use `HTTPException` for client errors.
- **Logging:** Some modules use `print()`, newer code should use `logging` module. Follow existing pattern in the file.
- **Settings:** Use `SettingsResolver.get("key", default)` to read config. Never read env vars directly.
- **Templates:** Jinja2 HTML files in `app/templates/`. Use inline CSS (no framework), Spanish labels, `POST` forms with `RedirectResponse`.
- **Database:** No Alembic. Tables created via `Base.metadata.create_all()` at startup. SQLite for dev, PostgreSQL for production.

## Domain Concepts

- **Pipeline stages:** Ingestion -> Grouping -> Extraction -> Cleaning -> Classification -> Scoring -> Review -> Editorial Build -> Validation -> Export
- **9 Categories:** AGENDA, NOTICIES, ESPORTS, TURISME_ACTIU, NENS_I_JOVES, CULTURA, GASTRONOMIA, CONSELLS, ENTREVISTES
- **4 Municipalities:** BERGUEDA, CERDANYA, MARESME, GENERAL
- **Hotfolder:** SMB (Synology) input with 3 folders (one per municipality). Each folder has a `processed/` subfolder.
- **Outfolder:** FTP output with 3 folders (one per municipality).
- **Settings categories:** general, telegram, inbox, outfolder, processing, publishing, ai, paths

## Key Files When Making Changes

- Adding a setting default: `app/services/settings/service.py` -> `initialize_defaults()`
- Adding a settings UI page: `app/templates/settings/` + `app/api/routes/settings.py`
- Adding a remote client: `app/services/inbox/clients/` + `app/services/remote/clients.py`
- Adding a test endpoint: `app/api/routes/settings.py` (under `# --- Test Endpoints ---`)
- DB models: `app/db/models.py`, `app/db/settings_models.py`, `app/db/inbox_models.py`
- Repositories: `app/db/repositories/all_repos.py`, `app/db/repositories/settings_repos.py`
- Pydantic schemas: `app/schemas/all_schemas.py`, `app/schemas/settings.py`

## Testing

- Framework: `pytest` with `fastapi.testclient.TestClient`
- Fixtures: `tmp_path` (built-in). `test_phase5.py` has an `autouse=True` fixture for DB setup.
- Mocking: `unittest.mock.patch`, `MagicMock`
- Test files are organized by project phase (`test_base.py`, `test_phase2.py`, etc.)
- **No conftest.py exists.** Create one if shared fixtures are needed.
- Tests run against SQLite in-memory or file DB. No test isolation by default.
- Always run tests after making changes to verify nothing is broken.

## Important Notes

- The virtual environment is at `venv/` (Python 3.11). Always activate before running commands.
- `smbclient` LSP errors are false positives - the package is installed in venv but not resolved by the LSP.
- Existing LSP type errors in `app/api/routes/settings.py` (UploadFile type issues) are pre-existing in the generic `save_settings_section` handler and are not caused by new code.
- The project is NOT a git repository. Do not run git commands unless explicitly asked.
- The `editorial.db` SQLite file in the project root is the development database.
- `SettingsResolver.reload(db)` must be called before reading settings in endpoints to pick up DB changes.
