from typing import List
from app.schemas.inbox import InboxBatch, InboxEntry
from app.services.inbox.clients.base import BaseRemoteInboxClient

class InboxBatchDiscoveryService:
    def __init__(self, client: BaseRemoteInboxClient):
        self.client = client

    def discover_batches(self) -> List[InboxBatch]:
        """
        Escanea la ruta base buscando candidatos a lotes.
        Reglas base:
        1. Las carpetas de primer nivel son lotes.
        2. Los archivos sueltos se pueden agrupar en un lote virtual o procesar individualmente.
           (En esta versión inicial, cada archivo suelto es un lote de 1 archivo).
        """
        list_result = self.client.list_entries()
        if not list_result.success:
            return []

        batches = []
        
        for entry in list_result.entries:
            if entry.is_dir:
                # Es una carpeta, listamos su contenido básico
                sub_list = self.client.list_entries(entry.relative_path)
                entries = sub_list.entries if sub_list.success else []
                
                # Filter out dirs for the batch representation if recursive is disabled
                # For now just take all allowed files inside it
                files_only = [f for f in entries if not f.is_dir]
                
                if files_only:
                    total_size = sum(f.size_bytes or 0 for f in files_only)
                    batches.append(InboxBatch(
                        batch_name=entry.name,
                        source_path=entry.full_path,
                        entries=files_only,
                        entry_count=len(files_only),
                        total_size_bytes=total_size
                    ))
            else:
                # Es un archivo suelto, se considera un lote de un solo archivo
                batches.append(InboxBatch(
                    batch_name=entry.name,
                    source_path=entry.full_path,
                    entries=[entry],
                    entry_count=1,
                    total_size_bytes=entry.size_bytes or 0
                ))

        return batches
