import asyncio
import threading
import contextlib
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.config.settings import settings
from app.db.base import Base
from app.db.session import engine
from app.api.routes.api_v1 import router as api_router
from app.api.routes.panel import router as panel_router
from app.api.routes.settings import router as settings_router
from app.api.routes.inbox import router as inbox_router
from app.api.routes.flows import router as flows_router
from app.services.watcher.service import WatcherService
from app.services.pipeline.orchestrator import PipelineOrchestrator

# Initialize DB tables
Base.metadata.create_all(bind=engine)

@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Gestión del ciclo de vida de la aplicación.
    Arrancamos el Watcher al iniciar y lo detenemos al apagar.
    """
    pipeline = PipelineOrchestrator(settings)
    
    # Callback the watcher calls when a new file/folder appears
    def on_new_content(path: str):
        # We process it synchronously in the background thread 
        # spawned by watchdog to avoid blocking the API
        try:
            pipeline.process_new_batch(path)
        except Exception as e:
            print(f"Error in background watcher processing: {e}")
            
    watcher = WatcherService(
        hot_folder_path=settings.SYNOLOGY_HOT_FOLDER,
        callback=on_new_content
    )
    
    # Iniciar watcher en un hilo separado
    watcher_thread = threading.Thread(target=watcher.start, daemon=True)
    watcher_thread.start()
    print(f"Watcher started on {settings.SYNOLOGY_HOT_FOLDER}")
    
    yield
    
    # Detener watcher al apagar
    watcher.stop()
    print("Watcher stopped")

app = FastAPI(
    title=settings.PROJECT_NAME,
    description="Automatización Editorial para WordPress",
    lifespan=lifespan
)

# API routes
app.include_router(api_router, prefix=settings.API_V1_STR)

# Panel HTML routes
app.include_router(panel_router)

# Settings Panel routes
app.include_router(settings_router, prefix="/settings")

# Inbox API routes
app.include_router(inbox_router, prefix="/api/v1/inbox")

# Flows API routes
app.include_router(flows_router)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
