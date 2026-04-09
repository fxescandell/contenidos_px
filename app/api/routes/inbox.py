from fastapi import APIRouter, Depends, HTTPException, Body
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.services.settings.service import SettingsResolver
from app.services.inbox.service import InboxService
from app.schemas.inbox import InboxConnectionTestResult, InboxListResult, InboxBatch

router = APIRouter()
inbox_service = InboxService()

@router.post("/test-active")
def test_active_connection(db: Session = Depends(get_db)):
    """Prueba la conexión del cliente inbox actualmente configurado"""
    SettingsResolver.reload(db)
    result = inbox_service.test_active_connection()
    return result.model_dump()

@router.get("/list", response_model=InboxListResult)
def list_active_inbox(db: Session = Depends(get_db)):
    """Lista el contenido raíz del inbox activo"""
    SettingsResolver.reload(db)
    settings = inbox_service.get_current_settings()
    
    from app.services.inbox.factory import InboxClientFactory
    client = InboxClientFactory.get_client(settings)
    if not client:
        raise HTTPException(status_code=400, detail="Modo de Inbox no soportado o desactivado")
        
    return client.list_entries()

@router.get("/discover")
def discover_batches(db: Session = Depends(get_db)):
    """Descubre y devuelve los lotes candidatos según las reglas configuradas"""
    SettingsResolver.reload(db)
    batches = inbox_service.discover_batches()
    return {"success": True, "batches": [b.model_dump() for b in batches]}

@router.post("/fetch-test")
def fetch_test_batch(batch_path: str = Body(..., embed=True), db: Session = Depends(get_db)):
    """Descarga de prueba de un lote a una carpeta temporal segura"""
    SettingsResolver.reload(db)
    import tempfile
    import os
    
    temp_dir = os.path.join(SettingsResolver.get("temp_folder_path") or tempfile.gettempdir(), "editorial_fetch_test")
    result = inbox_service.fetch_batch_to_working_dir(batch_path, temp_dir)
    return result.model_dump()