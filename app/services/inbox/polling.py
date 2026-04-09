import threading
import time
import os
from typing import List

from app.services.inbox.service import InboxService
from app.services.pipeline.orchestrator import PipelineOrchestrator
from app.config.settings import settings as app_settings
from app.core.inbox_enums import InboxMode
from app.services.settings.service import SettingsResolver

class InboxPollingService:
    def __init__(self, pipeline: PipelineOrchestrator):
        self.inbox_service = InboxService()
        self.pipeline = pipeline
        self.is_running = False
        self.thread = None
        
    def start(self, interval_seconds: int = 60):
        if self.is_running: return
        self.is_running = True
        self.thread = threading.Thread(target=self._poll_loop, args=(interval_seconds,), daemon=True)
        self.thread.start()
        print(f"Polling Service started with interval {interval_seconds}s")
        
    def stop(self):
        self.is_running = False
        if self.thread:
            self.thread.join(timeout=5)
            
    def _poll_loop(self, interval: int):
        while self.is_running:
            try:
                self._run_poll_cycle()
            except Exception as e:
                print(f"Polling error: {e}")
                
            # Sleep in chunks to allow responsive stop
            for _ in range(interval):
                if not self.is_running: break
                time.sleep(1)

    def _run_poll_cycle(self):
        settings = self.inbox_service.get_current_settings()
        
        if settings.mode == InboxMode.DISABLED:
            return
            
        # Discover batches
        batches = self.inbox_service.discover_batches()
        if not batches:
            return
            
        # Process each batch
        for batch in batches:
            # Here we would check the DB table `inbox_fetch_history` 
            # to see if this batch was already fetched.
            # Skipping that DB lookup for brevity, assuming the file is moved/deleted after process
            
            # Fetch it
            timestamp = str(int(time.time()))
            working_dir = os.path.join(SettingsResolver.get("working_folder_path") or app_settings.WORKING_DIRECTORY, f"{batch.batch_name}_{timestamp}")
            
            fetch_res = self.inbox_service.fetch_batch_to_working_dir(batch.source_path, working_dir)
            if fetch_res.success:
                # Trigger Pipeline
                # We point the pipeline to the local copy now
                target_to_process = os.path.join(working_dir, batch.batch_name) if settings.mode != InboxMode.LOCAL else working_dir
                
                self.pipeline.process_new_batch(target_to_process)
                
                # Finalize (Move or Delete on remote)
                action = "none"
                if settings.move_after_import: action = "move"
                elif settings.delete_after_import: action = "delete"
                
                if action != "none":
                    self.inbox_service.finalize_processed_batch(batch.source_path, action)
