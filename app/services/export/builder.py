import json
import hashlib
import os
from abc import ABC, abstractmethod
from typing import Dict, Any
from uuid import uuid4

from app.schemas.all_schemas import AdapterBuildResult, ExportBuildResult
from app.core.states import ExportStatus

class BaseExportBuilder(ABC):
    @abstractmethod
    def build_export(self, adapter_result: AdapterBuildResult) -> ExportBuildResult:
        pass

class WordPressJsonExportBuilder(BaseExportBuilder):
    def build_export(self, adapter_result: AdapterBuildResult) -> ExportBuildResult:
        from app.services.settings.service import SettingsResolver
        payload_dict = adapter_result.payload.model_dump()

        if adapter_result.raw_payload is not None:
            final_payload = adapter_result.raw_payload
        else:
            final_payload = {
                "source": "editorial_automation",
                "version": "1.0",
                "adapter": adapter_result.adapter_name,
                "data": payload_dict
            }
        
        json_str = json.dumps(final_payload, ensure_ascii=False, indent=2)
        checksum = hashlib.sha256(json_str.encode("utf-8")).hexdigest()
        
        export_id = uuid4()
        file_name = f"export_{adapter_result.canonical_id}_{checksum[:8]}.json"
        
        export_dir = SettingsResolver.get("export_output_path") or "/tmp/export_dir"
        os.makedirs(export_dir, exist_ok=True)
        
        export_path = os.path.join(export_dir, file_name)
        
        try:
            with open(export_path, "w", encoding="utf-8") as f:
                f.write(json_str)
            status = ExportStatus.WRITTEN
        except Exception as e:
            status = ExportStatus.FAILED
            export_path = None
            
        return ExportBuildResult(
            export_id=export_id,
            path=export_path,
            checksum=checksum,
            status=status
        )
