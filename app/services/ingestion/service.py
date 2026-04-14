import os
import shutil
import hashlib
from typing import Dict, Any, List
from datetime import datetime

from app.services.path_filters import is_ignored_source_folder

class IngestionService:
    def __init__(self, working_directory: str):
        self.working_directory = working_directory

    def ingest_batch(self, source_path: str) -> Dict[str, Any]:
        """
        Copies a batch (directory or single file) from the hot folder to the working directory.
        Calculates hashes and extracts metadata.
        """
        if not os.path.exists(source_path):
            raise FileNotFoundError(f"Source path {source_path} does not exist.")

        if os.path.isdir(source_path) and is_ignored_source_folder(os.path.basename(os.path.normpath(source_path))):
            raise ValueError(f"La carpeta '{os.path.basename(os.path.normpath(source_path))}' esta excluida del procesado.")

        batch_name = os.path.basename(source_path)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        batch_working_dir = os.path.join(self.working_directory, f"{batch_name}_{timestamp}")
        
        os.makedirs(batch_working_dir, exist_ok=True)
        
        files_metadata = []
        
        if os.path.isfile(source_path):
            dest_path = os.path.join(batch_working_dir, batch_name)
            shutil.copy2(source_path, dest_path)
            files_metadata.append(self._process_file(dest_path, batch_working_dir))
        else:
            for root, dirs, files in os.walk(source_path):
                dirs[:] = [directory for directory in dirs if not is_ignored_source_folder(directory)]
                for file in files:
                    if file.startswith('.'):  # Ignore hidden files like .DS_Store
                        continue
                        
                    src_file = os.path.join(root, file)
                    rel_path = os.path.relpath(src_file, source_path)
                    dest_file = os.path.join(batch_working_dir, rel_path)
                    
                    os.makedirs(os.path.dirname(dest_file), exist_ok=True)
                    shutil.copy2(src_file, dest_file)
                    
                    files_metadata.append(self._process_file(dest_file, batch_working_dir))

        # Calculate batch hash based on sorted file hashes
        files_metadata.sort(key=lambda x: x["relative_path"])
        batch_hash_input = "".join([f["sha256"] for f in files_metadata])
        batch_sha256 = hashlib.sha256(batch_hash_input.encode()).hexdigest()

        return {
            "external_name": batch_name,
            "original_path": source_path,
            "working_path": batch_working_dir,
            "batch_sha256": batch_sha256,
            "files": files_metadata
        }

    def _process_file(self, file_path: str, batch_working_dir: str) -> Dict[str, Any]:
        file_size = os.path.getsize(file_path)
        file_name = os.path.basename(file_path)
        extension = os.path.splitext(file_name)[1].lower()
        relative_path = os.path.relpath(file_path, batch_working_dir)
        
        sha256_hash = hashlib.sha256()
        with open(file_path, "rb") as f:
            for byte_block in iter(lambda: f.read(4096), b""):
                sha256_hash.update(byte_block)
                
        mime_type = self._guess_mime_type(extension)

        return {
            "original_path": file_path, # Contextual
            "working_path": file_path,
            "relative_path": relative_path,
            "file_name": file_name,
            "extension": extension,
            "mime_type": mime_type,
            "file_size_bytes": file_size,
            "sha256": sha256_hash.hexdigest()
        }

    def _guess_mime_type(self, extension: str) -> str:
        mime_types = {
            ".pdf": "application/pdf",
            ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            ".md": "text/markdown",
            ".markdown": "text/markdown",
            ".txt": "text/plain",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".png": "image/png"
        }
        return mime_types.get(extension, "application/octet-stream")
