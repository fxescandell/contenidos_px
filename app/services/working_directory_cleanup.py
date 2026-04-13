import os
import shutil
from typing import Iterable, Optional

from sqlalchemy.orm import Session

from app.core.states import BatchStatus
from app.db.repositories.all_repos import source_batch_repo
from app.db.session import SessionLocal
from app.services.settings.service import SettingsResolver


class WorkingDirectoryCleanupService:
    def cleanup_batch(self, batch: object) -> bool:
        if not self._is_enabled() or not batch:
            return False

        if getattr(batch, "status", None) != BatchStatus.FINISHED:
            return False

        return self._remove_working_path(getattr(batch, "working_path", ""))

    def cleanup_finished_batches(self, db: Optional[Session] = None, exclude_paths: Optional[Iterable[str]] = None) -> int:
        if not self._is_enabled():
            return 0

        excluded = {self._normalize_path(path) for path in (exclude_paths or []) if path}
        own_session = db is None
        session = db or SessionLocal()

        try:
            removed = 0
            for batch in source_batch_repo.list_by_status(session, BatchStatus.FINISHED):
                batch_path = self._normalize_path(getattr(batch, "working_path", ""))
                if not batch_path or batch_path in excluded:
                    continue
                if self._remove_working_path(batch_path):
                    removed += 1
            return removed
        finally:
            if own_session:
                session.close()

    def _is_enabled(self) -> bool:
        return bool(SettingsResolver.get("cleanup_working_folder_after_success", True))

    def _remove_working_path(self, path: str) -> bool:
        normalized = self._normalize_path(path)
        if not normalized or not self._is_path_eligible(normalized):
            return False
        if not os.path.exists(normalized):
            return False

        shutil.rmtree(normalized, ignore_errors=True)
        return not os.path.exists(normalized)

    def _is_path_eligible(self, path: str) -> bool:
        working_root = SettingsResolver.get("working_folder_path") or ""
        normalized_root = self._normalize_path(working_root)
        if not normalized_root:
            return False

        try:
            common = os.path.commonpath([normalized_root, path])
        except ValueError:
            return False

        return common == normalized_root and path != normalized_root

    def _normalize_path(self, path: str) -> str:
        if not path:
            return ""
        return os.path.abspath(path)


working_directory_cleanup_service = WorkingDirectoryCleanupService()
