import json
import os
from typing import Dict, Any, List, Optional, Tuple

from app.services.settings.service import SettingsResolver


class FlowExporter:
    def __init__(self):
        self.outfolder_mode = SettingsResolver.get("outfolder_mode", "ftp")
        self.outfolder_base = SettingsResolver.get("outfolder_base_path", "")

    def get_output_path(self, municipality: str, output_filename: str) -> str:
        return os.path.join(self.outfolder_base, municipality, output_filename)

    def write_json(self, municipality: str, filename: str, data: Dict[str, Any]) -> Tuple[bool, str]:
        folder = os.path.join(self.outfolder_base, municipality)
        try:
            os.makedirs(folder, exist_ok=True)
        except Exception:
            pass

        filepath = os.path.join(folder, filename)
        try:
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            return True, f"JSON escrito: {filepath}"
        except Exception as e:
            return False, f"Error escribiendo JSON: {e}"

    def upload_to_outfolder(self, municipality: str, filename: str, json_content: str) -> Tuple[bool, str]:
        if self.outfolder_mode == "local":
            folder = os.path.join(self.outfolder_base, municipality)
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
            try:
                from app.services.remote.clients import FtpOutfolderClient
                client = FtpOutfolderClient()
                remote_dir = os.path.join(self.outfolder_base, municipality).replace("\\", "/")
                remote_path = f"{remote_dir}/{filename}"
                client.upload_file_content(json_content.encode("utf-8"), remote_path)
                return True, f"JSON subido por FTP: {remote_path}"
            except Exception as e:
                return False, f"Error subiendo JSON por FTP: {e}"
