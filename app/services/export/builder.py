import json
import hashlib
import os
from abc import ABC, abstractmethod
from typing import Dict, Any
from uuid import uuid4

from app.schemas.all_schemas import AdapterBuildResult, ExportBuildResult
from app.core.states import ExportStatus
from app.config.settings import settings

class BaseExportBuilder(ABC):
    @abstractmethod
    def build_export(self, adapter_result: AdapterBuildResult) -> ExportBuildResult:
        pass

class WordPressJsonExportBuilder(BaseExportBuilder):
    def build_export(self, adapter_result: AdapterBuildResult) -> ExportBuildResult:
        payload_dict = adapter_result.payload.model_dump()
        
        # Add metadata or wrapper if needed by the importer
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
        
        # Ensure export directory exists
        os.makedirs(settings.EXPORT_DIRECTORY, exist_ok=True)
        
        export_path = os.path.join(settings.EXPORT_DIRECTORY, file_name)
        
        try:
            with open(export_path, "w", encoding="utf-8") as f:
                f.write(json_str)
            status = ExportStatus.WRITTEN
        except Exception as e:
            status = ExportStatus.FAILED
            # In a real app we would log the error
            export_path = None
            
        return ExportBuildResult(
            export_id=export_id,
            path=export_path,
            checksum=checksum,
            status=status
        )
