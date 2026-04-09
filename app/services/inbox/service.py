from typing import Optional, List, Tuple
from app.services.settings.service import SettingsResolver
from app.schemas.inbox import InboxConnectionSettings, InboxConnectionTestResult, InboxListResult, InboxBatch, InboxFetchResult
from app.core.inbox_enums import InboxMode
from app.services.inbox.factory import InboxClientFactory
from app.services.inbox.discovery import InboxBatchDiscoveryService

class InboxService:
    @staticmethod
    def get_current_settings() -> InboxConnectionSettings:
        mode_str = SettingsResolver.get("hot_folder_mode", "local")
        try:
            mode = InboxMode(mode_str)
        except ValueError:
            mode = InboxMode.DISABLED

        return InboxConnectionSettings(
            mode=mode,
            local_path=SettingsResolver.get("hot_folder_local_path"),
            host=SettingsResolver.get("remote_inbox_host"),
            port=int(SettingsResolver.get("remote_inbox_port", 21) or 21),
            username=SettingsResolver.get("remote_inbox_username"),
            password=SettingsResolver.get("remote_inbox_password"),
            base_path=SettingsResolver.get("remote_inbox_base_path", "/"),
            processed_path=SettingsResolver.get("remote_inbox_processed_path")
            # Other fields...
        )

    def test_active_connection(self) -> InboxConnectionTestResult:
        settings = self.get_current_settings()
        client = InboxClientFactory.get_client(settings)
        if not client:
            return InboxConnectionTestResult(
                success=False, message="Modo de Inbox no soportado o desactivado", tested_at=""
            )
        return client.test_connection()

    def discover_batches(self) -> List[InboxBatch]:
        settings = self.get_current_settings()
        client = InboxClientFactory.get_client(settings)
        if not client: return []
        
        discovery = InboxBatchDiscoveryService(client)
        return discovery.discover_batches()

    def fetch_batch_to_working_dir(self, batch_path: str, working_dir: str) -> InboxFetchResult:
        settings = self.get_current_settings()
        client = InboxClientFactory.get_client(settings)
        if not client: 
            return InboxFetchResult(success=False, message="Modo desactivado", source_path="", local_destination_path="", downloaded_files_count=0, skipped_files_count=0, total_bytes=0, fetched_at="")
        
        return client.fetch_batch(batch_path, working_dir)

    def finalize_processed_batch(self, remote_path: str, action: str) -> Tuple[bool, str]:
        settings = self.get_current_settings()
        client = InboxClientFactory.get_client(settings)
        if not client: return False, "Cliente no disponible"
        
        if action == "move":
            return client.move_processed_entry(remote_path)
        elif action == "delete":
            return client.delete_processed_entry(remote_path)
            
        return True, "Ninguna acción final configurada"
