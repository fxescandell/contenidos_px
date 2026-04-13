from types import SimpleNamespace
from unittest.mock import patch

from app.core.states import BatchStatus
from app.services.working_directory_cleanup import WorkingDirectoryCleanupService


def _mock_setting(root_path: str):
    def resolver(key, default=None):
        values = {
            "cleanup_working_folder_after_success": True,
            "working_folder_path": root_path,
        }
        return values.get(key, default)

    return resolver


@patch("app.services.working_directory_cleanup.SettingsResolver.get")
def test_cleanup_batch_removes_finished_directory(mock_get, tmp_path):
    working_root = tmp_path / "editorial_working"
    batch_dir = working_root / "batch_ok"
    batch_dir.mkdir(parents=True)
    (batch_dir / "doc1.pdf").write_text("contenido")

    mock_get.side_effect = _mock_setting(str(working_root))
    service = WorkingDirectoryCleanupService()
    batch = SimpleNamespace(status=BatchStatus.FINISHED, working_path=str(batch_dir))

    result = service.cleanup_batch(batch)

    assert result is True
    assert not batch_dir.exists()


@patch("app.services.working_directory_cleanup.SettingsResolver.get")
def test_cleanup_batch_keeps_failed_directory(mock_get, tmp_path):
    working_root = tmp_path / "editorial_working"
    batch_dir = working_root / "batch_failed"
    batch_dir.mkdir(parents=True)

    mock_get.side_effect = _mock_setting(str(working_root))
    service = WorkingDirectoryCleanupService()
    batch = SimpleNamespace(status=BatchStatus.FAILED, working_path=str(batch_dir))

    result = service.cleanup_batch(batch)

    assert result is False
    assert batch_dir.exists()


@patch("app.services.working_directory_cleanup.source_batch_repo.list_by_status")
@patch("app.services.working_directory_cleanup.SettingsResolver.get")
def test_cleanup_finished_batches_only_removes_paths_under_working_root(mock_get, mock_list, tmp_path):
    working_root = tmp_path / "editorial_working"
    removable_dir = working_root / "batch_old"
    external_dir = tmp_path / "otra_carpeta"
    removable_dir.mkdir(parents=True)
    external_dir.mkdir()

    mock_get.side_effect = _mock_setting(str(working_root))
    mock_list.return_value = [
        SimpleNamespace(status=BatchStatus.FINISHED, working_path=str(removable_dir)),
        SimpleNamespace(status=BatchStatus.FINISHED, working_path=str(external_dir)),
    ]

    service = WorkingDirectoryCleanupService()
    removed = service.cleanup_finished_batches(db=object())

    assert removed == 1
    assert not removable_dir.exists()
    assert external_dir.exists()
