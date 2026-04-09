import os
from ftplib import FTP
import paramiko
from smbclient import register_session, listdir, reset_connection_cache, open_file, remove, makedirs, stat as smb_stat, rename
from abc import ABC, abstractmethod
from typing import List, Tuple

class BaseRemoteInboxClient(ABC):
    @abstractmethod
    def test_connection(self) -> Tuple[bool, str]:
        pass

    @abstractmethod
    def list_contents(self, path: str) -> Tuple[bool, str, List[str]]:
        pass

class LocalFolderInboxClient(BaseRemoteInboxClient):
    def test_connection(self) -> Tuple[bool, str]:
        from app.services.settings.service import SettingsResolver
        path = SettingsResolver.get("hot_folder_local_path")
        
        if not path:
            return False, "La ruta local no está configurada."
            
        if not os.path.exists(path):
            try:
                os.makedirs(path, exist_ok=True)
                return True, f"Ruta local creada y validada: {path}"
            except Exception as e:
                return False, f"La ruta {path} no existe y no se pudo crear: {str(e)}"
                
        if not os.access(path, os.R_OK | os.W_OK):
            return False, f"Sin permisos de lectura/escritura en: {path}"
            
        return True, f"Conexión a ruta local validada: {path}"

    def list_contents(self, path: str) -> Tuple[bool, str, List[str]]:
        resolved_path = path or "/"
        if not os.path.exists(resolved_path):
            return False, f"La ruta {resolved_path} no existe.", []
            
        try:
            items = os.listdir(resolved_path)
            return True, "Ok", items[:20] # Limit for UI
        except Exception as e:
            return False, str(e), []

class FtpRemoteInboxClient(BaseRemoteInboxClient):
    def _get_config(self):
        from app.services.settings.service import SettingsResolver
        return {
            "host": SettingsResolver.get("remote_inbox_host"),
            "port": int(SettingsResolver.get("remote_inbox_port", 21) or 21),
            "user": SettingsResolver.get("remote_inbox_username"),
            "pass": SettingsResolver.get("remote_inbox_password"),
            "path": SettingsResolver.get("remote_inbox_base_path", "/")
        }

    def test_connection(self) -> Tuple[bool, str]:
        cfg = self._get_config()
        if not cfg["host"]:
            return False, "Falta configurar el Host FTP"
            
        ftp = FTP()
        try:
            ftp.connect(cfg["host"], cfg["port"], timeout=5)
            ftp.login(cfg["user"], cfg["pass"])
            ftp.cwd(cfg["path"])
            ftp.quit()
            return True, "Conexión FTP exitosa"
        except Exception as e:
            return False, f"Error conectando por FTP: {str(e)}"

    def list_contents(self, path: str) -> Tuple[bool, str, List[str]]:
        cfg = self._get_config()
        ftp = FTP()
        try:
            ftp.connect(cfg["host"], cfg["port"], timeout=5)
            ftp.login(cfg["user"], cfg["pass"])
            resolved_path = path or cfg["path"]
            ftp.cwd(resolved_path)
            items = ftp.nlst()
            ftp.quit()
            return True, "Ok", items[:20]
        except Exception as e:
            return False, str(e), []

class SftpRemoteInboxClient(BaseRemoteInboxClient):
    def _get_config(self):
        from app.services.settings.service import SettingsResolver
        return {
            "host": SettingsResolver.get("remote_inbox_host"),
            "port": int(SettingsResolver.get("remote_inbox_port", 22) or 22),
            "user": SettingsResolver.get("remote_inbox_username"),
            "pass": SettingsResolver.get("remote_inbox_password"),
            "path": SettingsResolver.get("remote_inbox_base_path", "/")
        }
        
    def test_connection(self) -> Tuple[bool, str]:
        cfg = self._get_config()
        if not cfg["host"]:
            return False, "Falta configurar el Host SFTP"
            
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        try:
            client.connect(
                hostname=cfg["host"], 
                port=cfg["port"], 
                username=cfg["user"], 
                password=cfg["pass"],
                timeout=5
            )
            sftp = client.open_sftp()
            sftp.chdir(cfg["path"])
            sftp.close()
            client.close()
            return True, "Conexión SFTP exitosa"
        except Exception as e:
            return False, f"Error conectando por SFTP: {str(e)}"

    def list_contents(self, path: str) -> Tuple[bool, str, List[str]]:
        cfg = self._get_config()
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        try:
            client.connect(
                hostname=cfg["host"], 
                port=cfg["port"], 
                username=cfg["user"], 
                password=cfg["pass"],
                timeout=5
            )
            sftp = client.open_sftp()
            resolved_path = path or cfg["path"]
            items = sftp.listdir(resolved_path)
            sftp.close()
            client.close()
            return True, "Ok", items[:20]
        except Exception as e:
            return False, str(e), []


class FtpOutfolderClient:
    def _get_config(self):
        from app.services.settings.service import SettingsResolver
        return {
            "host": SettingsResolver.get("outfolder_host"),
            "port": int(SettingsResolver.get("outfolder_port", 21) or 21),
            "user": SettingsResolver.get("outfolder_username"),
            "pass": SettingsResolver.get("outfolder_password"),
            "timeout": int(SettingsResolver.get("outfolder_timeout", 30) or 30),
            "passive": SettingsResolver.get("outfolder_passive_mode", True),
        }

    def test_connection(self) -> Tuple[bool, str]:
        cfg = self._get_config()
        if not cfg["host"]:
            return False, "Falta configurar el Host FTP de salida"
        ftp = FTP()
        try:
            ftp.connect(cfg["host"], cfg["port"], timeout=cfg["timeout"])
            ftp.login(cfg["user"], cfg["pass"])
            ftp.set_pasv(cfg["passive"])
            ftp.quit()
            return True, f"Conexion FTP salida exitosa ({cfg['host']}:{cfg['port']})"
        except Exception as e:
            return False, f"Error FTP salida: {str(e)}"

    def test_write_folder(self, base_path: str, delete_after: bool = True) -> Tuple[bool, str]:
        cfg = self._get_config()
        if not cfg["host"]:
            return False, "Falta configurar el Host FTP de salida"

        label = base_path.strip("/").split("/")[-1] or "raiz"
        test_filename = "test_connection.txt"
        test_content = f"Outfolder FTP write test\nFolder: {base_path}\nOK"
        results = []

        ftp = FTP()
        try:
            ftp.connect(cfg["host"], cfg["port"], timeout=cfg["timeout"])
            ftp.login(cfg["user"], cfg["pass"])
            ftp.set_pasv(cfg["passive"])

            try:
                ftp.cwd(base_path)
            except Exception:
                try:
                    ftp.cwd("/")
                    self._ftp_mkdirs(ftp, base_path)
                    ftp.cwd(base_path)
                except Exception as e2:
                    ftp.quit()
                    return False, f"[{label}] No se pudo crear/acceder a {base_path}: {e2}"

            from io import BytesIO
            ftp.storbinary(f"STOR {test_filename}", BytesIO(test_content.encode()))
            results.append(f"FTP [{label}]: escritura OK en {base_path}")

            if delete_after:
                ftp.delete(test_filename)
                results.append(f"FTP [{label}]: borrado OK")
            else:
                results.append(f"FTP [{label}]: archivo dejado en servidor (sin borrar)")

            ftp.quit()
            return True, " | ".join(results)
        except Exception as e:
            try:
                ftp.quit()
            except Exception:
                pass
            return False, f"Error FTP salida [{label}]: {str(e)}"

    def _ftp_mkdirs(self, ftp, path: str):
        dirs = path.strip("/").split("/")
        current = ""
        for d in dirs:
            current += "/" + d
            try:
                ftp.cwd(current)
            except Exception:
                try:
                    ftp.mkd(current)
                except Exception:
                    pass

    def list_subfolders(self, base_path: str) -> Tuple[bool, str, list]:
        cfg = self._get_config()
        ftp = FTP()
        try:
            ftp.connect(cfg["host"], cfg["port"], timeout=cfg["timeout"])
            ftp.login(cfg["user"], cfg["pass"])
            ftp.set_pasv(cfg["passive"])
            ftp.cwd(base_path or "/")
            lines = []
            ftp.dir(lines.append)
            result = []
            for line in lines:
                parts = line.split()
                if len(parts) >= 9:
                    name = " ".join(parts[8:])
                    is_dir = line.startswith("d")
                    result.append({"name": name, "is_dir": is_dir})
            ftp.quit()
            return True, "Ok", result
        except Exception as e:
            try:
                ftp.quit()
            except Exception:
                pass
            return False, str(e), []


class LocalOutfolderClient:
    def test_connection(self, path: str = "") -> Tuple[bool, str]:
        from app.services.settings.service import SettingsResolver
        target = path or SettingsResolver.get("outfolder_local_path")
        if not os.path.exists(target):
            try:
                os.makedirs(target, exist_ok=True)
                return True, f"Ruta creada: {target}"
            except Exception as e:
                return False, f"No se pudo crear {target}: {e}"
        if not os.access(target, os.R_OK | os.W_OK):
            return False, f"Sin permisos en: {target}"
        return True, f"Ruta local validada: {target}"

    def test_write_folder(self, base_path: str, delete_after: bool = True) -> Tuple[bool, str]:
        from app.services.settings.service import SettingsResolver
        local_base = SettingsResolver.get("outfolder_local_path") or ""
        if not local_base:
            return False, "Ruta base local de salida no configurada"
        clean_rel = base_path.lstrip("/") if base_path else ""
        full_path = os.path.join(local_base, clean_rel) if clean_rel else local_base
        label = base_path.strip("/").split("/")[-1] or "raiz"
        test_filename = "test_connection.txt"
        test_content = f"Outfolder Local write test\nFolder: {base_path}\nOK"
        try:
            os.makedirs(full_path, exist_ok=True)
            filepath = os.path.join(full_path, test_filename)
            with open(filepath, "w") as f:
                f.write(test_content)

            if delete_after:
                os.remove(filepath)
                return True, f"Local [{label}]: escritura + borrado OK ({full_path})"
            else:
                return True, f"Local [{label}]: archivo creado en {filepath} (sin borrar)"
        except Exception as e:
            return False, f"Error local [{label}]: {str(e)}"

    def list_subfolders(self, base_path: str) -> Tuple[bool, str, list]:
        from app.services.settings.service import SettingsResolver
        local_base = SettingsResolver.get("outfolder_local_path") or ""
        if not local_base:
            return False, "Ruta base local de salida no configurada", []
        clean_rel = base_path.lstrip("/") if base_path else ""
        full_path = os.path.join(local_base, clean_rel) if clean_rel else local_base
        if not os.path.exists(full_path):
            return False, f"Ruta {full_path} no existe.", []
        try:
            entries = os.listdir(full_path)
            result = [{"name": e, "is_dir": os.path.isdir(os.path.join(full_path, e))} for e in entries]
            return True, "Ok", result
        except Exception as e:
            return False, str(e), []


class SmbRemoteInboxClient(BaseRemoteInboxClient):
    def _get_config(self):
        from app.services.settings.service import SettingsResolver
        return {
            "host": SettingsResolver.get("remote_inbox_host") or "",
            "port": int(SettingsResolver.get("remote_inbox_port", 445) or 445),
            "user": SettingsResolver.get("remote_inbox_username") or "",
            "pass": SettingsResolver.get("remote_inbox_password") or "",
            "share": SettingsResolver.get("smb_share_name", "") or "",
            "domain": SettingsResolver.get("smb_domain", "") or "",
            "path": SettingsResolver.get("remote_inbox_base_path", "/") or "/",
            "timeout": int(SettingsResolver.get("remote_inbox_timeout", 30) or 30),
        }

    def _resolve_username(self, cfg):
        username = cfg["user"] or ""
        domain = cfg["domain"] or ""
        if domain and username:
            return f"{domain}\\{username}"
        return username

    def _build_unc_path(self, cfg, subpath=None):
        share = cfg["share"] or "share"
        base = cfg["path"].strip("/") or ""
        full = f"\\\\{cfg['host']}\\{share}"
        if base:
            full = f"{full}\\{base.replace('/', chr(92))}"
        if subpath:
            full = f"{full}\\{subpath.replace('/', chr(92))}"
        return full

    def test_connection(self) -> Tuple[bool, str]:
        cfg = self._get_config()
        if not cfg["host"]:
            return False, "Falta configurar el Host SMB"
        if not cfg["share"]:
            return False, "Falta configurar el Nombre del recurso compartido (Share)"

        unc = self._build_unc_path(cfg)
        try:
            register_session(
                server=cfg["host"],
                username=self._resolve_username(cfg) or None,
                password=cfg["pass"] or None,
                port=cfg["port"],
                connection_timeout=cfg["timeout"],
            )
            entries = listdir(unc)
            reset_connection_cache()
            return True, f"Conexión SMB exitosa. Recurso '{cfg['share']}' accesible ({len(entries)} elementos)"
        except Exception as e:
            try:
                reset_connection_cache()
            except Exception:
                pass
            return False, f"Error conectando por SMB: {str(e)}"

    def discover_shares(self, custom_names: list = None) -> Tuple[bool, str, list]:
        cfg = self._get_config()
        if not cfg["host"]:
            return False, "Falta configurar el Host SMB", []
        if not cfg["user"]:
            return False, "Falta configurar el Usuario", []

        shares_found = []
        try:
            register_session(
                server=cfg["host"],
                username=self._resolve_username(cfg) or None,
                password=cfg["pass"] or None,
                port=cfg["port"],
                connection_timeout=cfg["timeout"],
            )
        except Exception as e:
            try:
                reset_connection_cache()
            except Exception:
                pass
            return False, f"Error de autenticación: {e}", []

        candidates = [
            "IPC$", "ADMIN$", "C$", "D$", "E$", "F$", "DATA$",
            "public", "Public", "PUBLIC",
            "datos", "Datos", "DATA", "Data",
            "shared", "Shared", "SHARE", "Share",
            "compartido", "Compartido", "COMPARTIDO",
            "archivos", "Archivos", "files", "Files", "FILE",
            "scans", "Scans", "scan", "Scan", "entrada", "Entrada",
            "home", "users", "print$", "printers",
            "Per_pujar_al_web", "PER_PUJAR_AL_WEB",
            "Panxing_public", "panxing_public",
            "documentos", "Documentos",
        ]

        if custom_names:
            for name in custom_names:
                if name and name.strip() and name.strip() not in candidates:
                    candidates.insert(0, name.strip())

        if cfg["share"] and cfg["share"] not in candidates:
            candidates.insert(0, cfg["share"])

        seen = set()
        for share in candidates:
            if share in seen:
                continue
            seen.add(share)
            unc = f"\\\\{cfg['host']}\\{share}"
            try:
                entries = listdir(unc)
                shares_found.append({
                    "name": share,
                    "type": "special" if share.endswith("$") else "share",
                    "entries": len(entries),
                })
            except Exception:
                pass

        try:
            reset_connection_cache()
        except Exception:
            pass

        if not shares_found:
            return False, "No se encontraron recursos compartidos accesibles. Escribe un nombre personalizado en el campo de abajo y pulsa 'Probar nombre'.", []
        return True, f"{len(shares_found)} recurso(s) encontrado(s)", shares_found

    def list_share_folders(self, share_name: str) -> Tuple[bool, str, list]:
        cfg = self._get_config()
        if not share_name:
            return False, "Falta el nombre del recurso", []
        try:
            register_session(
                server=cfg["host"],
                username=self._resolve_username(cfg) or None,
                password=cfg["pass"] or None,
                port=cfg["port"],
                connection_timeout=cfg["timeout"],
            )
            unc = f"\\\\{cfg['host']}\\{share_name}"
            entries = listdir(unc)
            result = []
            for e in entries:
                name = str(e)
                is_dir = True
                try:
                    stat_info = smb_stat(f"{unc}\\{name}")
                    is_dir = bool(stat_info.st_file_attributes & 0x10)
                except Exception:
                    is_dir = True
                result.append({"name": name, "is_dir": is_dir})
            reset_connection_cache()
            return True, "Ok", result
        except Exception as e:
            try:
                reset_connection_cache()
            except Exception:
                pass
            return False, str(e), []

    def test_write(self) -> Tuple[bool, str]:
        cfg = self._get_config()
        if not cfg["host"]:
            return False, "Falta configurar el Host SMB"
        if not cfg["share"]:
            return False, "Falta configurar el Share"

        test_filename = "test_connection.txt"
        test_content = f"SMB write test - {cfg['host']}\\{cfg['share']}\nTimestamp: OK"
        results = []

        unc_base = self._build_unc_path(cfg)
        unc_processed = self._build_unc_path(cfg, cfg.get("processed_path", "/processed").strip("/"))

        try:
            register_session(
                server=cfg["host"],
                username=self._resolve_username(cfg) or None,
                password=cfg["pass"] or None,
                port=cfg["port"],
                connection_timeout=cfg["timeout"],
            )

            try:
                makedirs(unc_base, exist_ok=True)
            except Exception as e:
                reset_connection_cache()
                return False, f"No se pudo crear/acceder a la carpeta Hotfolder ({unc_base}): {e}"

            test_file_base = f"{unc_base}\\{test_filename}"
            try:
                with open_file(test_file_base, mode="w") as f:
                    f.write(test_content)
                results.append(f"Hotfolder: ESCRITURA OK ({unc_base})")
            except Exception as e:
                results.append(f"Hotfolder: FALLO escritura - {e}")
                reset_connection_cache()
                return False, " | ".join(results)

            try:
                remove(test_file_base)
                results.append("Hotfolder: BORRADO OK")
            except Exception as e:
                results.append(f"Hotfolder: borrado falló - {e}")

            try:
                makedirs(unc_processed, exist_ok=True)
                test_file_proc = f"{unc_processed}\\{test_filename}"
                with open_file(test_file_proc, mode="w") as f:
                    f.write(test_content)
                remove(test_file_proc)
                results.append(f"Procesados: ESCRITURA+BORRADO OK ({unc_processed})")
            except Exception as e:
                results.append(f"Procesados: FALLO - {e}")

            reset_connection_cache()
            if "FALLO" in "".join(results):
                return False, " | ".join(results)
            return True, " | ".join(results)
        except Exception as e:
            try:
                reset_connection_cache()
            except Exception:
                pass
            return False, f"Error: {e}"

    def test_write_folder(self, base_path: str, processed_path: str, delete_after: bool = True) -> Tuple[bool, str]:
        cfg = self._get_config()
        if not cfg["host"]:
            return False, "Falta configurar el Host SMB"
        if not cfg["share"]:
            return False, "Falta configurar el Share"

        test_filename = "test_connection.txt"
        test_content = f"SMB write test - {base_path} - PANXING\n"
        results = []
        label = base_path.strip("/").split("/")[-1] or "raiz"

        unc_share = f"\\\\{cfg['host']}\\{cfg['share']}"
        path_suffix = base_path.strip("/").replace("/", chr(92))
        unc_base = f"{unc_share}\\{path_suffix}" if path_suffix else unc_share
        proc_suffix = processed_path.strip("/").replace("/", chr(92))
        unc_processed = f"{unc_share}\\{proc_suffix}" if proc_suffix else unc_share

        try:
            register_session(
                server=cfg["host"],
                username=self._resolve_username(cfg) or None,
                password=cfg["pass"] or None,
                port=cfg["port"],
                connection_timeout=cfg["timeout"],
            )

            try:
                makedirs(unc_base, exist_ok=True)
            except Exception as e:
                reset_connection_cache()
                return False, f"[{label}] No se pudo crear {unc_base}: {e}"

            test_file = f"{unc_base}\\{test_filename}"
            try:
                fh = open_file(test_file, mode="w")
                fh.write(test_content)
                fh.flush()
                fh.close()
                if delete_after:
                    remove(test_file)
                    results.append(f"[{label}] Hotfolder: escritura + borrado OK ({unc_base})")
                else:
                    after = listdir(unc_base)
                    found = [str(x) for x in after if str(x).lower() == test_filename.lower()]
                    if found:
                        results.append(f"[{label}] Hotfolder: archivo DEJADO en {unc_base} ({len(after)} archivos en carpeta)")
                    else:
                        results.append(f"[{label}] AVISO: escrito OK pero no aparece al listar. Puede ser cache del NAS.")
            except Exception as e:
                results.append(f"[{label}] Hotfolder FALLO ({unc_base}): {e}")
                reset_connection_cache()
                return False, " | ".join(results)

            try:
                makedirs(unc_processed, exist_ok=True)
                proc_file = f"{unc_processed}\\{test_filename}"
                fh = open_file(proc_file, mode="w")
                fh.write(test_content)
                fh.flush()
                fh.close()
                if delete_after:
                    remove(proc_file)
                    results.append(f"[{label}] Procesados: escritura + borrado OK ({unc_processed})")
                else:
                    results.append(f"[{label}] Procesados: archivo DEJADO en {unc_processed}")
            except Exception as e:
                results.append(f"[{label}] Procesados FALLO ({unc_processed}): {e}")

            reset_connection_cache()
            has_error = any("FALLO" in r for r in results)
            if has_error:
                return False, " | ".join(results)
            return True, " | ".join(results)
        except Exception as e:
            try:
                reset_connection_cache()
            except Exception:
                pass
            return False, f"Error: {e}"

    def list_subfolders(self, base_path: str) -> Tuple[bool, str, list]:
        cfg = self._get_config()
        share = cfg["share"] or "share"
        unc = f"\\\\{cfg['host']}\\{share}"
        if base_path and base_path.strip("/"):
            unc = f"{unc}\\{base_path.strip('/').replace('/', chr(92))}"
        try:
            register_session(
                server=cfg["host"],
                username=self._resolve_username(cfg) or None,
                password=cfg["pass"] or None,
                port=cfg["port"],
                connection_timeout=cfg["timeout"],
            )
            entries = listdir(unc)
            result = []
            for e in entries:
                name = str(e)
                is_dir = True
                try:
                    stat_info = smb_stat(f"{unc}\\{name}")
                    is_dir = bool(stat_info.st_file_attributes & 0x10)
                except Exception:
                    is_dir = True
                result.append({"name": name, "is_dir": is_dir})
            reset_connection_cache()
            return True, "Ok", result
        except Exception as e:
            try:
                reset_connection_cache()
            except Exception:
                pass
            return False, str(e), []

    def list_contents(self, path: str) -> Tuple[bool, str, List[str]]:
        cfg = self._get_config()
        unc = self._build_unc_path(cfg, path)
        try:
            register_session(
                server=cfg["host"],
                username=self._resolve_username(cfg) or None,
                password=cfg["pass"] or None,
                port=cfg["port"],
                connection_timeout=cfg["timeout"],
            )
            entries = listdir(unc)
            reset_connection_cache()
            return True, "Ok", [str(e) for e in entries[:20]]
        except Exception as e:
            try:
                reset_connection_cache()
            except Exception:
                pass
            return False, str(e), []

    def move_to_processed(self, source_path: str, filenames: list) -> Tuple[bool, str]:
        from smbclient import listdir, makedirs, register_session, rename, reset_connection_cache, rmdir

        cfg = self._get_config()
        if not cfg["host"] or not cfg["share"]:
            return False, "SMB no configurado (falta host o share)"

        results = []
        moved = 0
        failed = 0

        source_path_str = str(source_path or "")
        if source_path_str.startswith("\\"):
            unc_source = source_path_str.rstrip("\\")
        else:
            path_suffix = source_path_str.strip("/").replace("/", chr(92))
            unc_source = f"\\\\{cfg['host']}\\{cfg['share']}\\{path_suffix}" if path_suffix else f"\\\\{cfg['host']}\\{cfg['share']}"
        unc_processed = f"{unc_source}\\processed"

        try:
            register_session(
                server=cfg["host"],
                username=self._resolve_username(cfg) or None,
                password=cfg["pass"] or None,
                port=cfg["port"],
                connection_timeout=cfg["timeout"],
            )

            try:
                makedirs(unc_processed, exist_ok=True)
            except Exception:
                pass

            for fname in filenames:
                src_file = f"{unc_source}\\{fname.replace('/', chr(92))}"
                dst_file = f"{unc_processed}\\{fname.replace('/', chr(92))}"
                dst_dir = dst_file.rsplit("\\", 1)[0]
                try:
                    makedirs(dst_dir, exist_ok=True)
                    rename(src_file, dst_file)
                    moved += 1
                except Exception as e:
                    failed += 1
                    results.append(f"FALLO moviendo {fname}: {e}")

            candidate_dirs = set()
            for fname in filenames:
                normalized = str(fname).replace("\\", "/")
                parent = normalized.rsplit("/", 1)[0] if "/" in normalized else ""
                while parent:
                    candidate_dirs.add(parent)
                    if "/" not in parent:
                        break
                    parent = parent.rsplit("/", 1)[0]

            for rel_dir in sorted(candidate_dirs, key=lambda d: d.count("/"), reverse=True):
                try:
                    unc_dir = f"{unc_source}\\{rel_dir.replace('/', chr(92))}"
                    if not listdir(unc_dir):
                        rmdir(unc_dir)
                except Exception:
                    pass

            reset_connection_cache()
            if failed == 0:
                return True, f"{moved} archivo(s) movidos a processed/"
            else:
                msg = f"{moved} movidos, {failed} con error"
                return False, msg + " - " + "; ".join(results) if results else msg
        except Exception as e:
            try:
                reset_connection_cache()
            except Exception:
                pass
            return False, f"Error moviendo archivos: {e}"
