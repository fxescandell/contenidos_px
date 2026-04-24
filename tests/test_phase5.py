import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from main import app
from app.db.session import get_db
from app.db.base import Base
from app.services.settings.service import SettingsResolver, SettingsService

# Override DB to ensure clean tests
SQLALCHEMY_DATABASE_URL = "sqlite:///./test_settings.db"
engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False})
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def override_get_db():
    try:
        db = TestingSessionLocal()
        yield db
    finally:
        db.close()

client = TestClient(app)

@pytest.fixture(autouse=True)
def setup_db():
    app.dependency_overrides[get_db] = override_get_db
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    # Reload settings resolver against new DB
    with TestingSessionLocal() as db:
        SettingsService.initialize_defaults(db)
        SettingsResolver.reload(db)
    yield
    Base.metadata.drop_all(bind=engine)
    app.dependency_overrides.pop(get_db, None)

def test_settings_dashboard_loads():
    response = client.get("/settings/")
    assert response.status_code == 200
    assert "Configuración del Sistema" in response.text
    assert "Selecciona una categoria de la izquierda" in response.text

def test_settings_general_section_loads():
    response = client.get("/settings/general")
    assert response.status_code == 200
    assert "project_name" in response.text

def test_settings_update_general_section():
    # Enviar formulario update
    response = client.post("/settings/general", data={
        "setting_project_name": "Nuevo WP Editorial",
        "type_project_name": "string",
        "setting_enable_auto_processing": "true",
        "type_enable_auto_processing": "boolean"
    }, follow_redirects=True)
    
    assert response.status_code == 200
    assert "Configuración guardada correctamente" in response.text
    assert "Nuevo WP Editorial" in response.text

def test_settings_telegram_secret_masked():
    # Guardar un token secreto
    client.post("/settings/telegram", data={
        "setting_telegram_bot_token": "my_secret_token_123",
        "type_telegram_bot_token": "string",
        "secret_telegram_bot_token": "on"
    })
    
    # Recargar la vista, no debe mostrar "my_secret_token_123" en claro
    response = client.get("/settings/telegram")
    assert "my_secret_token_123" not in response.text
    assert "********" in response.text

def test_settings_reload_cache():
    response = client.post("/settings/reload")
    assert response.status_code == 200
    assert response.json()["success"] == True
