import io
import json
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from main import app
from app.core.settings_enums import SettingType
from app.db.base import Base
from app.db.session import get_db
from app.schemas.settings import SettingItemUpdate
from app.services.settings.service import SettingsResolver, SettingsService


SQLALCHEMY_DATABASE_URL = "sqlite:///./test_workspace_modules.db"
engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False})
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


client = TestClient(app)


def setup_function(_):
    app.dependency_overrides[get_db] = override_get_db
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    with TestingSessionLocal() as db:
        SettingsService.initialize_defaults(db)
        SettingsResolver.reload(db)


def teardown_function(_):
    Base.metadata.drop_all(bind=engine)
    app.dependency_overrides.pop(get_db, None)


def test_workspace_preprocess_basic_flow(tmp_path: Path):
    with TestingSessionLocal() as db:
        SettingsService.update_section(
            db,
            "paths",
            [
                SettingItemUpdate(key="temp_folder_path", value=str(tmp_path / "temp"), value_type=SettingType.STRING),
            ],
            user="test",
        )
        SettingsResolver.reload(db)

    create_res = client.post("/api/v1/flows/workspace/preprocess/sessions")
    assert create_res.status_code == 200
    session_id = create_res.json()["session"]["id"]

    upload_res = client.post(
        f"/api/v1/flows/workspace/preprocess/sessions/{session_id}/upload",
        files=[("files", ("nota.txt", io.BytesIO(b"Texto de prueba para preprocesado"), "text/plain"))],
    )
    assert upload_res.status_code == 200
    assert upload_res.json()["success"] is True

    analyze_res = client.post(f"/api/v1/flows/workspace/preprocess/sessions/{session_id}/analyze")
    assert analyze_res.status_code == 200
    assert analyze_res.json()["success"] is True

    md_res = client.post(
        f"/api/v1/flows/workspace/preprocess/sessions/{session_id}/generate-md",
        json={
            "municipality": "BERGUEDA",
            "category": "AGENDA",
            "flow_id": "dummy-flow",
            "enable_web_enrichment": False,
            "web_query": "",
        },
    )
    assert md_res.status_code == 200
    data = md_res.json()
    assert data["success"] is True
    assert "## Resum" in data["markdown"]


def test_workspace_final_review_load_and_checks(tmp_path: Path):
    with TestingSessionLocal() as db:
        SettingsService.update_section(
            db,
            "paths",
            [SettingItemUpdate(key="temp_folder_path", value=str(tmp_path / "temp"), value_type=SettingType.STRING)],
            user="test",
        )
        SettingsResolver.reload(db)

    create_res = client.post("/api/v1/flows/workspace/final-review/sessions")
    assert create_res.status_code == 200
    session_id = create_res.json()["session"]["id"]

    export_payload = {
        "articles": [
            {"title": "Articulo A", "summary": "Resumen A", "body_html": "<p>Texto repetible</p>"},
            {"title": "Articulo B", "summary": "Resumen B", "body_html": "<p>Texto repetible</p>"},
        ]
    }
    upload = client.post(
        f"/api/v1/flows/workspace/final-review/sessions/{session_id}/load-export",
        files=[("file", ("export.json", io.BytesIO(json.dumps(export_payload).encode("utf-8")), "application/json"))],
    )
    assert upload.status_code == 200
    assert upload.json()["success"] is True

    checks = client.post(f"/api/v1/flows/workspace/final-review/sessions/{session_id}/run-checks")
    assert checks.status_code == 200
    checks_data = checks.json()
    assert checks_data["success"] is True
    assert checks_data["checks"]["issues_total"] >= 1


def test_workspace_pages_render_by_module():
    pages = {
        "dashboard": "Total Lotes",
        "manual-article": "Ejecucion manual segura",
        "manual-batches": "Carga por carpetas (categoria/articulo)",
        "preprocess": "Preprocesado de contenido",
        "final-review": "Revision final de exportaciones",
        "activity": "Utilidades de mantenimiento",
    }

    for page, marker in pages.items():
        resp = client.get(f"/workspace/{page}")
        assert resp.status_code == 200
        assert marker in resp.text
