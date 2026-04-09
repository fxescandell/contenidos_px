import pytest
from fastapi.testclient import TestClient
from uuid import uuid4

from main import app
from app.db.session import SessionLocal, engine
from app.db.base import Base

# Creamos las tablas para el test (usando SQLite en memoria por defecto o el de config)
Base.metadata.create_all(bind=engine)

client = TestClient(app)

def test_panel_home():
    response = client.get("/")
    assert response.status_code == 200
    assert "Lotes Recientes" in response.text
    assert "No hay lotes procesados todavía" in response.text or "Ver Detalle" in response.text

def test_api_process_manual_not_found():
    # Solo probamos la estructura del endpoint
    response = client.post("/api/v1/process-manual?path=/ruta/falsa")
    assert response.status_code == 200
    assert "Processing started" in response.json()["message"]

def test_api_reprocess_not_found():
    # Debe fallar porque no existe ese UUID en base de datos
    fake_id = str(uuid4())
    response = client.post(f"/api/v1/reprocess/{fake_id}")
    assert response.status_code == 404
    assert response.json()["detail"] == "Candidate not found"

def test_api_approve_not_found():
    fake_id = str(uuid4())
    response = client.post(f"/api/v1/approve/{fake_id}")
    assert response.status_code == 404
    assert response.json()["detail"] == "Candidate not found"
