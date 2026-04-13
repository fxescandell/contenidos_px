# AGENTS.md

## Runtime
- Use the repo venv and invoke Uvicorn through Python 3.11: `source venv/bin/activate` then `venv/bin/python -m uvicorn main:app --reload --host 0.0.0.0 --port 8000`. The repo depends on `pydantic-settings`; using a global Python/uvicorn can silently pick Python 3.9 and fail.
- `main.py` is the real app entrypoint. It runs `Base.metadata.create_all()`, initializes DB-backed defaults, reloads `SettingsResolver`, and only starts the watcher if both `START_WATCHER` and DB setting `enable_watcher` are enabled.

## Verified Commands
- Install deps: `pip install -r requirements.txt -r requirements_api.txt -r requirements_remote.txt -r requirements_watcher.txt`
- Run tests: `venv/bin/python -m pytest tests -v`
- Run a focused test: `venv/bin/python -m pytest tests/test_editorial_builder_strict_payload.py -v`
- Syntax-only verification is accepted when a targeted test does not exist: `venv/bin/python -m py_compile path/to/file.py`
- Docker dev/prod wrapper is `./deploy.sh [dev|prod] [up|down|restart|logs|ps|pull]`.

## Architecture That Matters
- The operational path is flow-driven, not watcher-driven. Flows are configured from the settings UI and processed through `app/services/pipeline/flow_service.py`.
- DB-backed settings are the source of truth at runtime. Read settings via `SettingsResolver.get(...)`; when adding a setting, update `app/services/settings/service.py` defaults and any relevant settings template/route together.
- Export JSON shape is category-specific and strict. `ejemplos_exportaciones/*.json` are executable reference templates; keep key names/order stable and update adapters + category settings + builder logic together if you touch export structure.
- Startup schema creation is still `Base.metadata.create_all()`; there is no Alembic workflow in use even though `alembic` is listed in requirements.
- `active_source_mode` affects both inbox and export behavior. Local/remote source settings and outfolder behavior are tightly coupled.

## Content / Editorial Rules Already Encoded
- Final editorial text must be in Catalan. Keep comments/user-facing strings in Spanish or Catalan, but code identifiers stay English.
- Agenda parsing is now code-driven in `app/services/editorial/agenda_parser.py`; do not push event splitting back into AI prompts. AI is used for headline/summary/intro/review, while event separation and agenda HTML structure are deterministic.
- The builder/final review layer (`app/services/editorial/builder.py`, `app/services/editorial/final_review.py`) preserves source content aggressively. Avoid “helpful” summarization changes that reduce source information, especially for `AGENDA` and listing-style articles.
- `processed/` folders are intentionally excluded from discovery/processing. Don’t reintroduce them into scans.
- Successful local flow exports move source files into the category-local `processed/` folder, not the municipality-level one.

## Database / Models
- SQLAlchemy models use UUID primary keys and SQLAlchemy 2 style. `SystemSetting` lives in `app/db/settings_models.py`, not `app/db/models.py`.
- JSON columns must only receive JSON-serializable data. UUIDs inside `structured_fields_json` must be converted to strings before persistence.

## UI / Templates
- The settings UI is server-rendered Jinja in `app/templates/`; it relies on inline CSS and plain JS, not a frontend build step.
- Recent work added collapsible cards for flows and AI connections plus a live activity modal in `settings/flows.html`; preserve those interaction patterns when extending the UI.

## Deployment / Env Gotchas
- Dev Docker uses SQLite at `/data/editorial.db`; prod Docker uses Postgres from `docker-compose.prod.yml`.
- Healthcheck endpoint used by Docker is `/api/v1/flows/active-mode`.
- Most operational configuration is expected to be changed from the panel, not by editing env vars after startup.

## Testing Priorities
- Prefer the smallest affected pytest file first; many business-rule regressions are already covered in focused files like `tests/test_agenda_parser.py`, `tests/test_editorial_builder_strict_payload.py`, `tests/test_category_settings_instructions.py`, `tests/test_flow_export_cleanup.py`, and `tests/test_ai_client_gemini.py`.
- When touching agenda/article generation, run the parser + builder tests together; they catch most regressions in structure, SEO refresh, image placement, and review logic.
