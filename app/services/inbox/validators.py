from typing import List, Tuple
from app.schemas.inbox import InboxConnectionSettings
from app.core.inbox_enums import InboxMode

class InboxSettingsValidator:
    @staticmethod
    def validate(settings: InboxConnectionSettings) -> Tuple[bool, List[str]]:
        errors = []
        
        if settings.mode == InboxMode.LOCAL:
            if not settings.local_path:
                errors.append("La ruta local es obligatoria si el modo es LOCAL.")
                
        elif settings.mode in [InboxMode.FTP, InboxMode.SFTP]:
            if not settings.host:
                errors.append("El Host es obligatorio para conexiones remotas.")
            if not settings.username:
                errors.append("El Usuario es obligatorio para conexiones remotas.")
                
            if settings.mode == InboxMode.SFTP:
                if not settings.use_key_auth and not settings.password:
                    errors.append("SFTP requiere contraseña o autenticación por clave privada.")
                if settings.use_key_auth and not settings.private_key_path:
                    errors.append("Ruta de clave privada obligatoria si se usa autenticación por clave.")
            else:
                # FTP
                if not settings.password:
                    errors.append("La contraseña es obligatoria para FTP.")
                    
            if settings.port is not None and (settings.port <= 0 or settings.port > 65535):
                errors.append("El puerto debe estar entre 1 y 65535.")
                
        if settings.delete_after_import and settings.move_after_import:
            errors.append("No puedes mover y borrar a la vez después de importar.")
            
        if settings.move_after_import and not settings.processed_path:
            errors.append("La ruta de procesados es obligatoria si se activa 'Mover después de importar'.")
            
        if settings.recursive_scan and settings.max_depth < 1:
            errors.append("La profundidad máxima debe ser al menos 1 si el escaneo recursivo está activo.")
            
        if settings.timeout_seconds <= 0:
            errors.append("El timeout debe ser mayor a 0.")
            
        return len(errors) == 0, errors
