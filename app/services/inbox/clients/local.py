import os
import shutil
from pathlib import Path
from typing import List, Tuple, Optional
from datetime import datetime

from app.schemas.inbox import (
    InboxConnectionSettings, InboxConnectionTestResult, InboxPathValidationResult,
    InboxListResult, InboxFetchResult, InboxEntry
)
from app.services.inbox.clients.base import BaseRemoteInboxClient
from app.services.path_filters import is_ignored_source_folder

class LocalFolderInboxClient(BaseRemoteInboxClient):
    
    def _resolve_safe_path(self, sub_path: str) -> Optional[Path]:
        base_path = Path(self.settings.local_path).resolve()
        
        if not sub_path or sub_path == "/" or sub_path == ".":
            return base_path
            
        # Limpiamos prefijos '/' para que la unión funcione como ruta relativa
        clean_sub_path = sub_path.lstrip('/')
        target_path = (base_path / clean_sub_path).resolve()
        
        # Path traversal protection
        try:
            target_path.relative_to(base_path)
            return target_path
        except ValueError:
            return None

    def test_connection(self) -> InboxConnectionTestResult:
        res = self.validate_base_path()
        return InboxConnectionTestResult(
            success=res.success,
            message=res.message,
            details=f"Path: {self.settings.local_path} | Exists: {res.exists} | Readable: {res.readable}",
            tested_at=datetime.now().isoformat()
        )

    def validate_base_path(self) -> InboxPathValidationResult:
        if not self.settings.local_path:
            return InboxPathValidationResult(
                success=False, exists=False, is_dir=False, readable=False,
                message="Ruta local no configurada", tested_at=datetime.now().isoformat()
            )
            
        p = Path(self.settings.local_path)
        exists = p.exists()
        is_dir = p.is_dir() if exists else False
        readable = os.access(p, os.R_OK) if exists else False
        writable = os.access(p, os.W_OK) if exists else False
        
        success = exists and is_dir and readable
        msg = "Ruta validada correctamente" if success else "Error validando ruta local"
        
        if not exists:
            msg = "La ruta local configurada no existe en el sistema."
        elif not is_dir:
            msg = "La ruta local configurada no es un directorio."
        elif not readable:
            msg = "La aplicación no tiene permisos de lectura sobre la ruta local."
            
        return InboxPathValidationResult(
            success=success, exists=exists, is_dir=is_dir, readable=readable, writable=writable,
            message=msg, tested_at=datetime.now().isoformat()
        )

    def list_entries(self, sub_path: Optional[str] = None) -> InboxListResult:
        target_path = self._resolve_safe_path(sub_path or "")
        
        if not target_path or not target_path.exists() or not target_path.is_dir():
            return InboxListResult(
                success=False, message="Ruta inválida o inexistente", listed_at=datetime.now().isoformat()
            )
            
        entries = []
        base_path = Path(self.settings.local_path).resolve()
        
        try:
            for item in target_path.iterdir():
                if self.settings.ignore_hidden_files and item.name.startswith('.'):
                    continue

                if item.is_dir() and is_ignored_source_folder(item.name):
                    continue
                    
                is_dir = item.is_dir()
                if not is_dir and not self._is_allowed_extension(item.name):
                    continue
                    
                stat = item.stat()
                entries.append(InboxEntry(
                    name=item.name,
                    full_path=str(item),
                    relative_path=str(item.relative_to(base_path)),
                    is_dir=is_dir,
                    size_bytes=stat.st_size if not is_dir else None,
                    modified_at=datetime.fromtimestamp(stat.st_mtime),
                    extension=item.suffix.lower() if not is_dir else None,
                    mime_type=self._get_mime_type(str(item)) if not is_dir else None
                ))
                
            return InboxListResult(
                success=True, entries=entries, message="Ok", listed_at=datetime.now().isoformat()
            )
        except Exception as e:
            return InboxListResult(
                success=False, message=str(e), listed_at=datetime.now().isoformat()
            )

    def fetch_entry(self, remote_path: str, local_destination_dir: str) -> InboxFetchResult:
        # For local, remote_path IS a local path, but we still treat it as the source
        return self.fetch_batch(remote_path, local_destination_dir)

    def fetch_batch(self, batch_path: str, local_destination_dir: str) -> InboxFetchResult:
        target_path = self._resolve_safe_path(batch_path)
        dest_dir = Path(local_destination_dir)
        
        if not target_path or not target_path.exists():
            return InboxFetchResult(
                success=False, source_path=batch_path, local_destination_path=local_destination_dir,
                downloaded_files_count=0, skipped_files_count=0, total_bytes=0,
                message=f"Ruta origen no encontrada: {batch_path}", fetched_at=datetime.now().isoformat()
            )
            
        os.makedirs(dest_dir, exist_ok=True)
        
        downloaded = 0
        skipped = 0
        total_bytes = 0
        
        try:
            if target_path.is_file():
                if self.settings.ignore_hidden_files and target_path.name.startswith('.'):
                    skipped += 1
                elif not self._is_allowed_extension(target_path.name):
                    skipped += 1
                else:
                    dest_file = dest_dir / target_path.name
                    shutil.copy2(target_path, dest_file)
                    downloaded += 1
                    total_bytes += dest_file.stat().st_size
            else:
                # Directorio
                for root, dirs, files in os.walk(target_path):
                    if self.settings.ignore_hidden_files:
                        dirs[:] = [d for d in dirs if not d.startswith('.')]

                    dirs[:] = [d for d in dirs if not is_ignored_source_folder(d)]
                         
                    root_path = Path(root)
                    rel_to_target = root_path.relative_to(target_path)
                    
                    for file in files:
                        if self.settings.ignore_hidden_files and file.startswith('.'):
                            skipped += 1
                            continue
                            
                        if not self._is_allowed_extension(file):
                            skipped += 1
                            continue
                            
                        src_file = root_path / file
                        dest_file_dir = dest_dir / rel_to_target
                        os.makedirs(dest_file_dir, exist_ok=True)
                        
                        dest_file = dest_file_dir / file
                        shutil.copy2(src_file, dest_file)
                        downloaded += 1
                        total_bytes += dest_file.stat().st_size
                        
            return InboxFetchResult(
                success=True, source_path=batch_path, local_destination_path=local_destination_dir,
                downloaded_files_count=downloaded, skipped_files_count=skipped, total_bytes=total_bytes,
                message="Copia completada", fetched_at=datetime.now().isoformat()
            )
        except Exception as e:
            return InboxFetchResult(
                success=False, source_path=batch_path, local_destination_path=local_destination_dir,
                downloaded_files_count=downloaded, skipped_files_count=skipped, total_bytes=total_bytes,
                message=str(e), fetched_at=datetime.now().isoformat()
            )

    def move_processed_entry(self, remote_path: str) -> Tuple[bool, str]:
        target_path = self._resolve_safe_path(remote_path)
        if not target_path or not target_path.exists():
            return False, "Ruta no encontrada"
            
        if not self.settings.processed_path:
            return False, "processed_path no configurado"
            
        proc_dir = Path(self.settings.processed_path)
        os.makedirs(proc_dir, exist_ok=True)
        
        dest_path = proc_dir / target_path.name
        
        # Evitar sobreescrituras añadiendo timestamp si existe
        if dest_path.exists():
            dest_path = proc_dir / f"{target_path.name}_{int(datetime.now().timestamp())}"
            
        try:
            shutil.move(str(target_path), str(dest_path))
            return True, f"Movido a {dest_path}"
        except Exception as e:
            return False, str(e)

    def delete_processed_entry(self, remote_path: str) -> Tuple[bool, str]:
        target_path = self._resolve_safe_path(remote_path)
        if not target_path or not target_path.exists():
            return False, "Ruta no encontrada"
            
        try:
            if target_path.is_file():
                target_path.unlink()
            else:
                shutil.rmtree(target_path)
            return True, "Borrado correctamente"
        except Exception as e:
            return False, str(e)
