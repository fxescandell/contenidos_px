from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from main import app
from app.db.base import Base
from app.db.session import get_db
from app.schemas.settings import SettingItemUpdate
from app.core.settings_enums import SettingType
from app.services.settings.service import SettingsResolver, SettingsService


SQLALCHEMY_DATABASE_URL = "sqlite:///./test_manual_home_workflow.db"
engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False})
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


client = TestClient(app)


def _set_paths(working_path: Path, temp_path: Path):
    with TestingSessionLocal() as db:
        SettingsService.initialize_defaults(db)
        SettingsService.update_section(
            db,
            "paths",
            [
                SettingItemUpdate(key="working_folder_path", value=str(working_path), value_type=SettingType.STRING),
                SettingItemUpdate(key="temp_folder_path", value=str(temp_path), value_type=SettingType.STRING),
            ],
            user="test",
        )
        SettingsResolver.reload(db)


def _create_file(path: Path, content: str = "x"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


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


def test_manual_cleanup_soft_preview_and_execute(tmp_path):
    working = tmp_path / "editorial_working"
    temp = tmp_path / "editorial_temp"
    _set_paths(working, temp)

    _create_file(working / "job_1" / "work.txt", "working")
    _create_file(temp / "manual_flow_drafts" / "draft_1" / "a.txt", "flow")
    _create_file(temp / "manual_tree_uploads" / "session_1" / "b.txt", "tree")
    _create_file(temp / "other_cache" / "keep.txt", "keep")

    preview_resp = client.post(
        "/api/v1/flows/manual/maintenance/cleanup",
        json={"mode": "soft", "dry_run": True},
    )
    assert preview_resp.status_code == 200
    preview = preview_resp.json()
    assert preview["success"] is True
    assert preview["dry_run"] is True
    assert preview["planned"] >= 2
    assert preview["removed"] == 0

    exec_resp = client.post(
        "/api/v1/flows/manual/maintenance/cleanup",
        json={"mode": "soft", "dry_run": False},
    )
    assert exec_resp.status_code == 200
    execution = exec_resp.json()
    assert execution["success"] is True
    assert execution["dry_run"] is False
    assert execution["removed"] >= 2

    assert not (temp / "manual_flow_drafts").exists()
    assert not (temp / "manual_tree_uploads").exists()
    assert (temp / "other_cache").exists()
    assert (working / "job_1").exists()


def test_manual_ai_health_without_active_connection_returns_error():
    resp = client.get("/api/v1/flows/manual/inbox/ai-health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is False
    assert "No hay conexion IA activa" in data["message"]
