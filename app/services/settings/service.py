import json as _json
from typing import Any, Dict, Optional, List

from sqlalchemy.orm import Session
from app.db.session import SessionLocal
from app.db.repositories.settings_repos import system_setting_repo, settings_audit_repo
from app.schemas.settings import SettingItemUpdate
from app.core.settings_enums import SettingType
from app.config.settings import settings as env_settings

class SettingsResolver:
    """
    Combina la configuración de la Base de Datos con las variables de entorno (fallback).
    Implementa un caché en memoria muy básico para no saturar la BD si se lee muchas veces,
    aunque en un pipeline por lotes, leer de BD una vez por lote es aceptable.
    """
    _cache: Dict[str, Any] = {}
    _cache_loaded: bool = False

    @classmethod
    def reload(cls, db: Session):
        cls._cache.clear()
        all_settings = system_setting_repo.get_all(db)
        for s in all_settings:
            val = s.value_json.get("value")
            # Unmasking secrets is not done here, resolver just returns the stored value
            # Note: secrets should ideally be encrypted, but for this exercise we store them 
            # and just mask them in the UI.
            cls._cache[s.key] = val
        cls._cache_loaded = True

    @classmethod
    def get(cls, key: str, default: Any = None) -> Any:
        if not cls._cache_loaded:
            # Sincrónico, en producción esto debería llamarse al inicio
            with SessionLocal() as db:
                cls.reload(db)
                
        # 1. Intentar BD
        if key in cls._cache:
            return cls._cache[key]
            
        # 2. Intentar Env (app.config.settings)
        env_val = getattr(env_settings, key.upper(), None)
        if env_val is not None:
            return env_val
            
        # 3. Fallback
        return default

class SettingsService:
    @staticmethod
    def get_section(db: Session, category: str) -> List[Dict[str, Any]]:
        settings = system_setting_repo.get_by_category(db, category)
        result = []
        for s in settings:
            val = s.value_json.get("value")
            if s.is_secret and val:
                val = "********" # Mask secret for UI
            
            result.append({
                "key": s.key,
                "value": val,
                "value_type": s.value_type,
                "category": s.category,
                "is_secret": s.is_secret,
                "description": s.description
            })
        return result

    @staticmethod
    def update_section(db: Session, category: str, items: List[SettingItemUpdate], user: str = "system"):
        for item in items:
            existing = system_setting_repo.get_by_key(db, item.key)
            
            # If secret and value is the mask, skip update
            if item.is_secret and item.value == "********":
                continue
                
            old_val = None
            if existing:
                old_val = existing.value_json.get("value")
                
                # Check if changed
                if old_val == item.value:
                    continue
                    
                existing.value_json = {"value": item.value}
                existing.value_type = item.value_type
                existing.is_secret = item.is_secret
                existing.description = item.description or existing.description
                existing.updated_by = user
                system_setting_repo.update(db, db_obj=existing, obj_in={})
            else:
                system_setting_repo.create(db, obj_in={
                    "key": item.key,
                    "value_json": {"value": item.value},
                    "value_type": item.value_type,
                    "category": category,
                    "is_secret": item.is_secret,
                    "description": item.description,
                    "updated_by": user
                })
                
            # Log Audit
            old_masked = "********" if existing and existing.is_secret else str(old_val)
            new_masked = "********" if item.is_secret else str(item.value)
            
            settings_audit_repo.create(db, obj_in={
                "key": item.key,
                "section": category,
                "action": "UPDATE" if existing else "CREATE",
                "old_value_masked": old_masked if existing else None,
                "new_value_masked": new_masked,
                "performed_by": user
            })
            
        # Reload cache
        SettingsResolver.reload(db)

    @staticmethod
    def initialize_defaults(db: Session):
        defaults = [
            # General
            {"key": "project_name", "value": "Editorial WP", "type": SettingType.STRING, "cat": "general", "desc": "Nombre visible del proyecto en el panel y exports"},
            {"key": "app_env", "value": "production", "type": SettingType.STRING, "cat": "general", "desc": "Entorno: production (sin logs detallados) o development (logs verbose)"},
            {"key": "enable_auto_processing", "value": True, "type": SettingType.BOOLEAN, "cat": "general", "desc": "Procesa automaticamente los archivos que llegan al hotfolder cuando se detectan"},
            {"key": "enable_watcher", "value": True, "type": SettingType.BOOLEAN, "cat": "general", "desc": "Vigila el hotfolder en segundo plano buscando archivos nuevos. Si se desactiva, solo se procesa por peticiones manuales o API"},
            {"key": "watcher_interval_seconds", "value": "10", "type": SettingType.INTEGER, "cat": "general", "desc": "Cada cuantos segundos revisa el hotfolder (aplica al reiniciar la app)"},
            {"key": "min_file_size_kb", "value": "1", "type": SettingType.INTEGER, "cat": "general", "desc": "Tamanio minimo en KB para procesar un archivo. Ignora archivos mas pequenos (basura, .DS_Store)"},
            {"key": "enable_telegram_on_error", "value": True, "type": SettingType.BOOLEAN, "cat": "general", "desc": "Envia notificacion por Telegram cuando un lote falla"},
            {"key": "max_parallel_batches", "value": "3", "type": SettingType.INTEGER, "cat": "general", "desc": "Maximo de lotes que se procesan en paralelo"},
            {"key": "active_source_mode", "value": "smb", "type": SettingType.STRING, "cat": "general", "desc": "Modo activo de entrada/salida: smb (SMB+FTP) o local"},
            
            # Telegram
            {"key": "telegram_enabled", "value": False, "type": SettingType.BOOLEAN, "cat": "telegram", "desc": "Activa las notificaciones por Telegram para alertas y errores del pipeline"},
            {"key": "telegram_bot_token", "value": "", "type": SettingType.STRING, "cat": "telegram", "secret": True, "desc": "Token del bot de Telegram (obtenido desde @BotFather)"},
            {"key": "telegram_chat_id", "value": "", "type": SettingType.STRING, "cat": "telegram", "desc": "ID del chat o canal donde el bot envia las notificaciones"},
            
            # Hot Folder / Inbox
            {"key": "hot_folder_mode", "value": "local", "type": SettingType.STRING, "cat": "inbox", "desc": "Modo de conexión: local, ftp, sftp o smb"},
            {"key": "hot_folder_local_path", "value": "/tmp/hot_folder", "type": SettingType.STRING, "cat": "inbox", "desc": "Ruta local para carpetas (modo local)"},
            {"key": "remote_inbox_host", "value": "", "type": SettingType.STRING, "cat": "inbox", "desc": "Host del servidor FTP/SFTP/SMB (ej: ftp.ejemplo.com)"},
            {"key": "remote_inbox_port", "value": "21", "type": SettingType.INTEGER, "cat": "inbox", "desc": "Puerto (FTP: 21, SFTP: 22, SMB: 445)"},
            {"key": "remote_inbox_username", "value": "", "type": SettingType.STRING, "cat": "inbox", "desc": "Usuario de autenticación FTP/SFTP/SMB"},
            {"key": "remote_inbox_password", "value": "", "type": SettingType.STRING, "cat": "inbox", "secret": True, "desc": "Contraseña del servidor FTP/SFTP/SMB"},
            {"key": "remote_inbox_base_path", "value": "/", "type": SettingType.STRING, "cat": "inbox", "desc": "Ruta base en el servidor remoto"},
            {"key": "remote_inbox_passive_mode", "value": True, "type": SettingType.BOOLEAN, "cat": "inbox", "desc": "Modo pasivo FTP (recomendado detrás de NAT/firewall)"},
            {"key": "remote_inbox_processed_path", "value": "/processed", "type": SettingType.STRING, "cat": "inbox", "desc": "Ruta donde se mueven los lotes procesados"},
            {"key": "remote_inbox_timeout", "value": "30", "type": SettingType.INTEGER, "cat": "inbox", "desc": "Timeout de conexión en segundos"},
            {"key": "smb_share_name", "value": "", "type": SettingType.STRING, "cat": "inbox", "desc": "Nombre del recurso compartido SMB (ej: datos, publico)"},
            {"key": "smb_domain", "value": "", "type": SettingType.STRING, "cat": "inbox", "desc": "Dominio de autenticación SMB (opcional, ej: WORKGROUP)"},
        ]
        default_folders = [
            {"name": "Bergueda", "base_path": "/Bergueda", "processed_path": "/Bergueda/processed", "enabled": True},
            {"name": "Cerdanya", "base_path": "/Cerdanya", "processed_path": "/Cerdanya/processed", "enabled": True},
            {"name": "Maresme", "base_path": "/Maresme", "processed_path": "/Maresme/processed", "enabled": True},
        ]
        defaults.append({"key": "hotfolder_folders", "value": _json.dumps(default_folders), "type": SettingType.STRING, "cat": "inbox", "desc": "Lista de carpetas hotfolder (JSON)"})

        # Outfolder (FTP salida)
        outfolder_defaults = [
            {"key": "outfolder_mode", "value": "ftp", "type": SettingType.STRING, "cat": "outfolder", "desc": "Modo de salida: ftp o local"},
            {"key": "outfolder_local_path", "value": "/tmp/out_folder", "type": SettingType.STRING, "cat": "outfolder", "desc": "Ruta local para salida (modo local)"},
            {"key": "outfolder_host", "value": "", "type": SettingType.STRING, "cat": "outfolder", "desc": "Host del servidor FTP de salida"},
            {"key": "outfolder_port", "value": "21", "type": SettingType.INTEGER, "cat": "outfolder", "desc": "Puerto FTP de salida"},
            {"key": "outfolder_username", "value": "", "type": SettingType.STRING, "cat": "outfolder", "desc": "Usuario FTP de salida"},
            {"key": "outfolder_password", "value": "", "type": SettingType.STRING, "cat": "outfolder", "secret": True, "desc": "Contraseña FTP de salida"},
            {"key": "outfolder_timeout", "value": "30", "type": SettingType.INTEGER, "cat": "outfolder", "desc": "Timeout FTP de salida (segundos)"},
            {"key": "outfolder_passive_mode", "value": True, "type": SettingType.BOOLEAN, "cat": "outfolder", "desc": "Modo pasivo FTP de salida"},
        ]
        outfolder_folders = [
            {"name": "Bergueda", "base_path": "/Bergueda", "enabled": True},
            {"name": "Cerdanya", "base_path": "/Cerdanya", "enabled": True},
            {"name": "Maresme", "base_path": "/Maresme", "enabled": True},
        ]
        outfolder_defaults.append({"key": "outfolder_folders", "value": _json.dumps(outfolder_folders), "type": SettingType.STRING, "cat": "outfolder", "desc": "Lista de carpetas outfolder (JSON)"})
        defaults += outfolder_defaults

        # OCR & AI
        defaults += [
            {"key": "ocr_engine", "value": "disabled", "type": SettingType.STRING, "cat": "ai", "desc": "Motor de OCR: tesseract, paddleocr, azure_vision, ai_vision o disabled (sin OCR)"},
            {"key": "ocr_language", "value": "cat+spa", "type": SettingType.STRING, "cat": "ai", "desc": "Idiomas del OCR separados por + (ej: cat+spa, eng, spa)"},
            {"key": "ocr_dpi", "value": "300", "type": SettingType.INTEGER, "cat": "ai", "desc": "DPI de escaneo para OCR (recomendado: 300)"},
            {"key": "ocr_vision_connection_id", "value": "", "type": SettingType.STRING, "cat": "ai", "desc": "ID de la conexion LLM utilizada para OCR con Vision IA"},
            {"key": "llm_connections", "value": "[]", "type": SettingType.JSON, "cat": "ai", "desc": "Lista de conexiones LLM configuradas (JSON)"},
            {"key": "llm_enabled", "value": False, "type": SettingType.BOOLEAN, "cat": "ai", "desc": "Activa el uso de LLM para clasificacion, resumen y generacion de contenido"},
            {"key": "llm_provider", "value": "openai", "type": SettingType.STRING, "cat": "ai", "desc": "Proveedor LLM activo (sincronizado desde conexiones)"},
            {"key": "llm_api_key", "value": "", "type": SettingType.STRING, "cat": "ai", "secret": True, "desc": "Clave API del proveedor LLM activo"},
            {"key": "llm_model", "value": "gpt-4o-mini", "type": SettingType.STRING, "cat": "ai", "desc": "Modelo LLM activo (sincronizado desde conexiones)"},
            {"key": "llm_temperature", "value": "0.3", "type": SettingType.FLOAT, "cat": "ai", "desc": "Temperatura del LLM (0.0 = determinista, 1.0 = creativo)"},
            
            # Processing
            {"key": "pipeline_mode", "value": "folder_based", "type": SettingType.STRING, "cat": "processing", "desc": "Modo del pipeline: folder_based (basado en flujos/carpetas) o automatic (clasificacion automatica)"},
            {"key": "auto_publish_enabled", "value": False, "type": SettingType.BOOLEAN, "cat": "processing", "desc": "Publica automaticamente los articulos tras completar el pipeline"},
            {"key": "scan_interval_seconds", "value": "60", "type": SettingType.INTEGER, "cat": "processing", "desc": "Intervalo en segundos entre escaneos del hotfolder (solo si el watcher esta activo)"},
            {"key": "batch_size_limit", "value": "50", "type": SettingType.INTEGER, "cat": "processing", "desc": "Maximo de archivos por lote antes de forzar el procesamiento"},
            {"key": "enable_retry_on_failure", "value": True, "type": SettingType.BOOLEAN, "cat": "processing", "desc": "Reintenta automaticamente los lotes que fallan (hasta 3 intentos)"},
            {"key": "skip_duplicate_files", "value": True, "type": SettingType.BOOLEAN, "cat": "processing", "desc": "Ignora archivos duplicados basandose en el hash del contenido"},
            {"key": "enable_ocr", "value": False, "type": SettingType.BOOLEAN, "cat": "processing", "desc": "Extrae texto de imagenes con OCR antes de la clasificacion"},

            # Publishing
            {"key": "export_mode", "value": "per_batch", "type": SettingType.STRING, "cat": "publishing", "desc": "Modo de exportacion: per_batch (un JSON por lote) o per_article (un JSON por articulo)"},
            {"key": "wp_api_url", "value": "", "type": SettingType.STRING, "cat": "publishing", "desc": "URL de la API REST de WordPress (ej: https://ejemplo.com/wp-json/wp/v2)"},
            {"key": "wp_username", "value": "", "type": SettingType.STRING, "cat": "publishing", "desc": "Usuario de la API de WordPress (con permisos de editor)"},
            {"key": "wp_app_password", "value": "", "type": SettingType.STRING, "cat": "publishing", "secret": True, "desc": "Contrasena de aplicacion de WordPress (generada en Perfil > Contrasenas de aplicacion)"},
            {"key": "wp_default_status", "value": "draft", "type": SettingType.STRING, "cat": "publishing", "desc": "Estado inicial de los articulos publicados: draft, publish o pending"},
            {"key": "wp_default_author_id", "value": "1", "type": SettingType.INTEGER, "cat": "publishing", "desc": "ID del autor por defecto para los articulos importados"},
            {"key": "export_include_media", "value": True, "type": SettingType.BOOLEAN, "cat": "publishing", "desc": "Incluye las URLs de las imagenes/medios en el JSON exportado"},

            # Rutas locales
            {"key": "working_folder_path", "value": "/tmp/editorial_working", "type": SettingType.STRING, "cat": "paths", "desc": "Carpeta temporal donde se descomprimen y procesan los archivos del pipeline"},
            {"key": "export_output_path", "value": "/tmp/editorial_export", "type": SettingType.STRING, "cat": "paths", "desc": "Carpeta donde se guardan los JSON exportados antes de enviar al outfolder"},
            {"key": "temp_folder_path", "value": "/tmp/editorial_temp", "type": SettingType.STRING, "cat": "paths", "desc": "Carpeta para archivos temporales (se limpia automaticamente)"},
            {"key": "log_folder_path", "value": "logs", "type": SettingType.STRING, "cat": "paths", "desc": "Carpeta donde se guardan los logs de la aplicacion"},
        ]
        
        for d in defaults:
            existing = system_setting_repo.get_by_key(db, d["key"])
            if existing:
                continue
            system_setting_repo.create(db, obj_in={
                "key": d["key"],
                "value_json": {"value": d["value"]},
                "value_type": d["type"],
                "category": d["cat"],
                "is_secret": d.get("secret", False),
                "description": d.get("desc", "")
            })
