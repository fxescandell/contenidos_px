import os
from pathlib import Path
from typing import List, Tuple, Optional
from datetime import datetime
from contextlib import contextmanager

import paramiko

from app.schemas.inbox import (
    InboxConnectionSettings, InboxConnectionTestResult, InboxPathValidationResult,
    InboxListResult, InboxFetchResult, InboxEntry
)
from app.services.inbox.clients.base import BaseRemoteInboxClient

class SftpRemoteInboxClient(BaseRemoteInboxClient):
    
    @contextmanager
    def _connect(self):
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        
        connect_kwargs = {
            "hostname": self.settings.host,
            "port": self.settings.port or 22,
            "username": self.settings.username,
            "timeout": self.settings.timeout_seconds
        }
        
        if self.settings.use_key_auth and self.settings.private_key_path:
            connect_kwargs["key_filename"] = self.settings.private_key_path
            if self.settings.private_key_passphrase:
                connect_kwargs["passphrase"] = self.settings.private_key_passphrase
        else:
            connect_kwargs["password"] = self.settings.password
            
        try:
            client.connect(**connect_kwargs)
            sftp = client.open_sftp()
            yield sftp
        finally:
            try:
                sftp.close()
            except: pass
            try:
                client.close()
            except: pass

    def _normalize_path(self, *parts) -> str:
        path = "/".join(p.strip("/") for p in parts if p)
        if not path.startswith("/"):
            path = "/" + path
        return path

    def test_connection(self) -> InboxConnectionTestResult:
        try:
            with self._connect() as sftp:
                sftp.chdir(self.settings.base_path)
            return InboxConnectionTestResult(
                success=True, message="Conexión SFTP exitosa", details="Auth ok", tested_at=datetime.now().isoformat()
            )
        except Exception as e:
            return InboxConnectionTestResult(
                success=False, message="Error de conexión SFTP", details=str(e), tested_at=datetime.now().isoformat()
            )

    def validate_base_path(self) -> InboxPathValidationResult:
        try:
            with self._connect() as sftp:
                try:
                    stat = sftp.stat(self.settings.base_path)
                    from stat import S_ISDIR
                    is_dir = S_ISDIR(stat.st_mode)
                    
                    # Probar escritura
                    test_file = self._normalize_path(self.settings.base_path, ".test_write")
                    try:
                        with sftp.open(test_file, 'w') as f:
                            f.write("test")
                        sftp.remove(test_file)
                        writable = True
                    except:
                        writable = False
                        
                    return InboxPathValidationResult(
                        success=is_dir, exists=True, is_dir=is_dir, readable=True, writable=writable,
                        message="Ruta SFTP validada" if is_dir else "La ruta no es un directorio",
                        tested_at=datetime.now().isoformat()
                    )
                except FileNotFoundError:
                    return InboxPathValidationResult(
                        success=False, exists=False, is_dir=False, readable=False, writable=False,
                        message="La ruta SFTP no existe", tested_at=datetime.now().isoformat()
                    )
        except Exception as e:
            return InboxPathValidationResult(
                success=False, exists=False, is_dir=False, readable=False, writable=False,
                message=str(e), tested_at=datetime.now().isoformat()
            )

    def list_entries(self, sub_path: Optional[str] = None) -> InboxListResult:
        target_path = self._normalize_path(self.settings.base_path, sub_path or "")
        entries = []
        
        try:
            with self._connect() as sftp:
                for attr in sftp.listdir_attr(target_path):
                    if self.settings.ignore_hidden_files and attr.filename.startswith('.'):
                        continue
                        
                    from stat import S_ISDIR
                    is_dir = S_ISDIR(attr.st_mode)
                    
                    if not is_dir and not self._is_allowed_extension(attr.filename):
                        continue
                        
                    full_path = self._normalize_path(target_path, attr.filename)
                    rel_path = full_path.replace(self.settings.base_path, "").lstrip("/")
                    
                    entries.append(InboxEntry(
                        name=attr.filename, full_path=full_path, relative_path=rel_path,
                        is_dir=is_dir, size_bytes=attr.st_size if not is_dir else None, 
                        modified_at=datetime.fromtimestamp(attr.st_mtime) if attr.st_mtime else None,
                        extension="." + attr.filename.split('.')[-1].lower() if "." in attr.filename and not is_dir else None,
                        mime_type=self._get_mime_type(attr.filename) if not is_dir else None
                    ))
                    
            return InboxListResult(
                success=True, entries=entries, message="Ok", listed_at=datetime.now().isoformat()
            )
        except Exception as e:
            return InboxListResult(
                success=False, message=str(e), listed_at=datetime.now().isoformat()
            )

    def fetch_entry(self, remote_path: str, local_destination_dir: str) -> InboxFetchResult:
        return self.fetch_batch(remote_path, local_destination_dir)

    def fetch_batch(self, batch_path: str, local_destination_dir: str) -> InboxFetchResult:
        os.makedirs(local_destination_dir, exist_ok=True)
        downloaded = 0
        total_bytes = 0
        
        try:
            with self._connect() as sftp:
                try:
                    stat = sftp.stat(batch_path)
                    from stat import S_ISDIR
                    if S_ISDIR(stat.st_mode):
                        # Descarga 1 nivel (no recursiva profunda por simplicidad)
                        for attr in sftp.listdir_attr(batch_path):
                            if self.settings.ignore_hidden_files and attr.filename.startswith('.'): continue
                            if S_ISDIR(attr.st_mode): continue # Skip folders
                            if not self._is_allowed_extension(attr.filename): continue
                            
                            remote_file = self._normalize_path(batch_path, attr.filename)
                            local_file = os.path.join(local_destination_dir, attr.filename)
                            sftp.get(remote_file, local_file)
                            downloaded += 1
                            total_bytes += attr.st_size
                    else:
                        name = batch_path.split('/')[-1]
                        local_file = os.path.join(local_destination_dir, name)
                        sftp.get(batch_path, local_file)
                        downloaded += 1
                        total_bytes += stat.st_size
                        
                except Exception as inner_e:
                    raise inner_e
                    
            return InboxFetchResult(
                success=True, source_path=batch_path, local_destination_path=local_destination_dir,
                downloaded_files_count=downloaded, skipped_files_count=0, total_bytes=total_bytes,
                message="Descarga SFTP completada", fetched_at=datetime.now().isoformat()
            )
        except Exception as e:
            return InboxFetchResult(
                success=False, source_path=batch_path, local_destination_path=local_destination_dir,
                downloaded_files_count=downloaded, skipped_files_count=0, total_bytes=total_bytes,
                message=f"Error descargando desde SFTP: {str(e)}", fetched_at=datetime.now().isoformat()
            )

    def move_processed_entry(self, remote_path: str) -> Tuple[bool, str]:
        if not self.settings.processed_path:
            return False, "Ruta de procesados no configurada"
            
        name = remote_path.split('/')[-1]
        dest_path = self._normalize_path(self.settings.processed_path, name)
        
        try:
            with self._connect() as sftp:
                try:
                    sftp.mkdir(self.settings.processed_path)
                except IOError:
                    pass # Ya existe
                sftp.rename(remote_path, dest_path)
            return True, f"Movido a {dest_path}"
        except Exception as e:
            return False, str(e)

    def delete_processed_entry(self, remote_path: str) -> Tuple[bool, str]:
        try:
            with self._connect() as sftp:
                stat = sftp.stat(remote_path)
                from stat import S_ISDIR
                if S_ISDIR(stat.st_mode):
                    return False, "Borrado de carpetas SFTP no soportado por seguridad en V1"
                else:
                    sftp.remove(remote_path)
            return True, "Borrado correctamente"
        except Exception as e:
            return False, str(e)