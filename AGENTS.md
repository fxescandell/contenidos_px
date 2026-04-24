# AGENTS.md

## Runtime / boot
- Use repo Python, not global tools: `venv/bin/python -m uvicorn main:app --reload --host 0.0.0.0 --port 8000`.
- `main.py` is the real entrypoint: it calls `Base.metadata.create_all()`, initializes DB defaults (`SettingsService.initialize_defaults`), reloads `SettingsResolver`, and mounts `/static` from `app/static`.
- Watcher starts only when both are enabled: env `START_WATCHER` and DB setting `enable_watcher`.

## Commands that are easy to guess wrong
- Install deps from all requirement files: `pip install -r requirements.txt -r requirements_api.txt -r requirements_remote.txt -r requirements_watcher.txt`.
- Full tests: `venv/bin/python -m pytest tests -v`.
- Focused tests (high value):
  - `venv/bin/python -m pytest tests/test_agenda_parser.py -v`
  - `venv/bin/python -m pytest tests/test_editorial_builder_strict_payload.py -v`
  - `venv/bin/python -m pytest tests/test_flow_export_cleanup.py -v`
  - `venv/bin/python -m pytest tests/test_workspace_modules.py -v`
  - `venv/bin/python -m pytest tests/test_manual_home_workflow.py -v`
- Docker wrapper: `./deploy.sh [dev|prod] [up|down|restart|logs|ps|pull]` (requires `.env` or `.env.production`).

## Architecture realities
- Runtime behavior is DB-settings-driven. When adding/changing a setting, update defaults in `app/services/settings/service.py` and the corresponding settings route/template.
- Active source mode (`active_source_mode`) controls both inbox and export paths; mode changes happen via `/api/v1/flows/switch-mode` and are consumed across flow/export/workspace services.
- Workspace UI is server-rendered Jinja + static JS/CSS (`app/templates/index.html`, `app/templates/workspace/pages/*`, `app/static/js/workspace/*`, `app/static/css/workspace/index.css`); no frontend build pipeline.
- Batch/workspace asset cache-busting is mtime-based from `app/api/routes/panel.py` (`_compute_workspace_assets_version`).

## Editorial and pipeline constraints
- Final editorial output must remain in Catalan (enforced in builder/final review prompts/services).
- Agenda/event splitting is deterministic code in `app/services/editorial/agenda_parser.py`; do not move event segmentation back into prompts.
- Preserve export payload shape and key ordering per category (`ejemplos_exportaciones/*.json` + builder/adapters/category settings).
- Source discovery intentionally ignores `processed` folders (`app/services/path_filters.py`); do not re-include them.

## Data model gotchas
- `SystemSetting` model is in `app/db/settings_models.py` (not `app/db/models.py`).
- JSON DB fields must be JSON-serializable; convert UUIDs to strings before persisting (notably in structured/editorial JSON blobs).

## Deployment facts
- Dev compose uses SQLite (`/data/editorial.db`); prod compose uses Postgres (`docker-compose.prod.yml`).
- Docker healthcheck endpoint: `/api/v1/flows/active-mode`.
