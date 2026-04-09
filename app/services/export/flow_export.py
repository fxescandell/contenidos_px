import json
import os
import shutil
from io import BytesIO
from typing import Dict, Any, List, Optional, Tuple

from app.services.settings.service import SettingsResolver


class FlowExporter:
    def __init__(self):
        pass

    def _get_active_mode(self) -> str:
        return SettingsResolver.get("active_source_mode", "smb") or "smb"

    def _get_local_outfolder_base(self) -> str:
        return SettingsResolver.get("outfolder_local_path") or "/tmp/out_folder"

    def _get_local_hotfolder_path(self) -> str:
        return SettingsResolver.get("hot_folder_local_path") or "/tmp/hot_folder"

    def _get_outfolder_mapping(self, municipality: str, mode: str) -> Dict[str, str]:
        settings_key = "outfolder_local_folders" if mode == "local" else "outfolder_folders"
        raw_value = SettingsResolver.get(settings_key, "[]")

        try:
            folders = json.loads(raw_value) if isinstance(raw_value, str) else raw_value
        except Exception:
            folders = []

        if not isinstance(folders, list):
            folders = []

        normalized_municipality = (municipality or "").strip().lower()
        for item in folders:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name", "")).strip().lower()
            if name != normalized_municipality:
                continue
            if item.get("enabled") is False:
                continue
            return {
                "name": str(item.get("name", municipality) or municipality),
                "base_path": str(item.get("base_path", "") or ""),
            }

        return {
            "name": str(municipality or "").strip() or municipality,
            "base_path": f"/{municipality.lstrip('/')}"
        }

    def _get_public_base_url(self) -> str:
        return str(SettingsResolver.get("outfolder_public_base_url") or "").rstrip("/")

    def _build_public_image_url(self, municipality_folder_name: str, filename: str) -> str:
        base_url = self._get_public_base_url()
        if not base_url:
            return ""
        return f"{base_url}/{municipality_folder_name.strip('/')}/images/{filename}"

    def plan_image_uploads(self, municipality: str, images: List[Any]) -> List[Dict[str, Any]]:
        mode = self._get_active_mode()
        mapping = self._get_outfolder_mapping(municipality, mode)
        base_path = mapping.get("base_path", "")
        folder_name = mapping.get("name", municipality)
        image_dir = f"{base_path.rstrip('/')}/images" if base_path else "/images"

        planned = []
        for image in images:
            optimized_local_path = getattr(image, "optimized_path", None)
            thumbnail_local_path = getattr(image, "thumbnail_path", None)
            optimized_name = os.path.basename(optimized_local_path) if optimized_local_path else ""
            thumbnail_name = os.path.basename(thumbnail_local_path) if thumbnail_local_path else ""
            planned.append({
                "source_file_id": str(getattr(image, "source_file_id", "") or ""),
                "optimized_local_path": optimized_local_path,
                "thumbnail_local_path": thumbnail_local_path,
                "optimized_remote_path": f"{image_dir}/{optimized_name}" if optimized_name else "",
                "thumbnail_remote_path": f"{image_dir}/{thumbnail_name}" if thumbnail_name else "",
                "optimized_public_url": self._build_public_image_url(folder_name, optimized_name) if optimized_name else "",
                "thumbnail_public_url": self._build_public_image_url(folder_name, thumbnail_name) if thumbnail_name else "",
            })
        return planned

    def upload_image_assets(self, municipality: str, image_plans: List[Dict[str, Any]]) -> Tuple[bool, str, List[Dict[str, Any]]]:
        mode = self._get_active_mode()
        uploaded: List[Dict[str, Any]] = []

        for plan in image_plans:
            try:
                optimized_local_path = plan.get("optimized_local_path") or ""
                thumbnail_local_path = plan.get("thumbnail_local_path") or ""

                if optimized_local_path and os.path.exists(optimized_local_path):
                    if mode == "local":
                        self._copy_local_asset(plan.get("optimized_remote_path", ""), optimized_local_path)
                    else:
                        with open(optimized_local_path, "rb") as f:
                            ok, msg = self._upload_ftp(plan.get("optimized_remote_path", ""), f.read())
                        if not ok:
                            return False, msg, uploaded

                if thumbnail_local_path and os.path.exists(thumbnail_local_path):
                    if mode == "local":
                        self._copy_local_asset(plan.get("thumbnail_remote_path", ""), thumbnail_local_path)
                    else:
                        with open(thumbnail_local_path, "rb") as f:
                            ok, msg = self._upload_ftp(plan.get("thumbnail_remote_path", ""), f.read())
                        if not ok:
                            return False, msg, uploaded

                uploaded.append(plan)
            except Exception as e:
                return False, f"Error subiendo imagenes: {e}", uploaded

        return True, f"{len(uploaded)} imagen(es) subida(s)", uploaded

    def _copy_local_asset(self, remote_like_path: str, local_source_path: str) -> None:
        base = self._get_local_outfolder_base()
        clean_rel = remote_like_path.lstrip("/") if remote_like_path else ""
        destination = os.path.join(base, clean_rel) if clean_rel else os.path.join(base, os.path.basename(local_source_path))
        os.makedirs(os.path.dirname(destination), exist_ok=True)
        shutil.copy2(local_source_path, destination)

    def upload_to_outfolder(self, municipality: str, filename: str, json_content: str) -> Tuple[bool, str]:
        mode = self._get_active_mode()
        target_folder = self._get_outfolder_mapping(municipality, mode).get("base_path", "")

        if mode == "local":
            base = self._get_local_outfolder_base()
            clean_rel = target_folder.lstrip("/") if target_folder else ""
            folder = os.path.join(base, clean_rel) if clean_rel else base
            try:
                os.makedirs(folder, exist_ok=True)
            except Exception:
                pass
            filepath = os.path.join(folder, filename)
            try:
                with open(filepath, "w", encoding="utf-8") as f:
                    f.write(json_content)
                return True, f"JSON escrito localmente: {filepath}"
            except Exception as e:
                return False, f"Error escribiendo JSON local: {e}"
        else:
            remote_dir = target_folder if str(target_folder).startswith("/") else f"/{str(target_folder).lstrip('/')}"
            remote_path = f"{remote_dir}/{filename}"
            ok, msg = self._upload_ftp(remote_path, json_content.encode("utf-8"))
            return ok, msg

    def move_to_processed(self, source_path: str, filenames: List[str]) -> Tuple[bool, str]:
        mode = self._get_active_mode()
        if mode == "local":
            return self._move_local_processed(source_path, filenames)
        else:
            return self._move_smb_processed(source_path, filenames)

    def _move_local_processed(self, source_path: str, filenames: List[str]) -> Tuple[bool, str]:
        try:
            source_dir = source_path
            if not os.path.isdir(source_dir):
                return False, f"Ruta no es un directorio: {source_dir}"

            processed_dir = os.path.join(source_dir, "..", "processed")
            os.makedirs(processed_dir, exist_ok=True)

            moved = []
            for fname in filenames:
                src = os.path.join(source_dir, fname)
                if not os.path.exists(src):
                    continue
                dst = os.path.join(processed_dir, fname)
                if os.path.exists(dst):
                    base, ext = os.path.splitext(fname)
                    dst = os.path.join(processed_dir, f"{base}_{int(os.path.getmtime(src))}{ext}")
                shutil.move(src, dst)
                moved.append(fname)

            self._cleanup_empty_local_dirs(source_dir, filenames)

            return True, f"{len(moved)} ficheros movidos a {processed_dir}"
        except Exception as e:
            return False, f"Error moviendo ficheros locales: {e}"

    def _cleanup_empty_local_dirs(self, source_dir: str, filenames: List[str]) -> None:
        candidate_dirs = set()
        for fname in filenames:
            parent = os.path.dirname(fname)
            while parent and parent not in (".", os.sep):
                candidate_dirs.add(os.path.join(source_dir, parent))
                parent = os.path.dirname(parent)

        for directory in sorted(candidate_dirs, key=lambda d: d.count(os.sep), reverse=True):
            if not os.path.isdir(directory):
                continue
            try:
                if not os.listdir(directory):
                    os.rmdir(directory)
            except Exception:
                pass

    def _move_smb_processed(self, source_unc: str, filenames: List[str]) -> Tuple[bool, str]:
        try:
            from app.services.remote.clients import SmbRemoteInboxClient
            client = SmbRemoteInboxClient()
            ok, msg = client.move_to_processed(source_unc, filenames)
            return ok, msg
        except Exception as e:
            return False, f"Error moviendo ficheros SMB: {e}"

    def _upload_ftp(self, remote_path: str, content: bytes) -> Tuple[bool, str]:
        try:
            from ftplib import FTP
            from app.services.settings.service import SettingsResolver
            host = SettingsResolver.get("outfolder_host") or ""
            port = int(SettingsResolver.get("outfolder_port", 21) or 21)
            user = SettingsResolver.get("outfolder_username") or ""
            passwd = SettingsResolver.get("outfolder_password") or ""
            timeout = int(SettingsResolver.get("outfolder_timeout", 30) or 30)
            passive = SettingsResolver.get("outfolder_passive_mode", True)

            if not host:
                return False, "Falta configurar Host FTP de salida"

            ftp = FTP()
            ftp.connect(host, port, timeout=timeout)
            ftp.login(user, passwd)
            ftp.set_pasv(passive)

            dirname = "/".join(remote_path.split("/")[:-1])
            filename = remote_path.split("/")[-1]
            if dirname:
                try:
                    ftp.cwd(dirname)
                except Exception:
                    dirs = dirname.strip("/").split("/")
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

            ftp.storbinary(f"STOR {filename}", BytesIO(content))
            ftp.quit()
            return True, f"JSON subido por FTP: {remote_path}"
        except Exception as e:
            return False, f"Error subiendo JSON por FTP: {e}"
