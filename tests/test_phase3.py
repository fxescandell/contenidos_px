import pytest
import os
import shutil
from unittest.mock import patch, MagicMock

from app.services.ingestion.service import IngestionService
from app.services.watcher.service import WatcherService, HotFolderHandler
from app.services.pipeline.orchestrator import PipelineOrchestrator
from app.config.settings import settings

def test_ingestion_service_single_file(tmp_path):
    # Setup test directories
    working_dir = tmp_path / "working_dir"
    hot_folder = tmp_path / "hot_folder"
    working_dir.mkdir()
    hot_folder.mkdir()
    
    # Create a test file
    test_file = hot_folder / "test.docx"
    test_file.write_text("dummy content")
    
    ingestion = IngestionService(str(working_dir))
    result = ingestion.ingest_batch(str(test_file))
    
    assert result["external_name"] == "test.docx"
    assert "working_path" in result
    assert len(result["files"]) == 1
    assert result["files"][0]["file_name"] == "test.docx"
    assert result["files"][0]["extension"] == ".docx"
    assert result["files"][0]["mime_type"] == "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

def test_ingestion_service_directory(tmp_path):
    # Setup test directories
    working_dir = tmp_path / "working_dir"
    hot_folder = tmp_path / "hot_folder"
    batch_dir = hot_folder / "maresme_noticies"
    working_dir.mkdir()
    batch_dir.mkdir(parents=True)
    
    # Create test files
    (batch_dir / "doc1.pdf").write_text("pdf content")
    (batch_dir / "img1.jpg").write_text("img content")
    
    ingestion = IngestionService(str(working_dir))
    result = ingestion.ingest_batch(str(batch_dir))
    
    assert result["external_name"] == "maresme_noticies"
    assert len(result["files"]) == 2
    
    extensions = [f["extension"] for f in result["files"]]
    assert ".pdf" in extensions
    assert ".jpg" in extensions

@patch("app.services.watcher.service.time.sleep")
def test_hot_folder_handler(mock_sleep, tmp_path):
    mock_callback = MagicMock()
    handler = HotFolderHandler(mock_callback)
    
    # Create a dummy event
    class DummyEvent:
        def __init__(self, src_path):
            self.src_path = src_path
            
    # Trigger event
    test_path = str(tmp_path / "test_file.txt")
    handler.on_created(DummyEvent(test_path))
    
    # Wait for thread to finish (since it sleeps and calls)
    # the sleep is mocked so it returns immediately
    # but we need to wait for the thread to actually execute the mock
    import time
    time.sleep(0.1) 
    
    mock_callback.assert_called_once_with(test_path)
    
def test_hot_folder_handler_ignores_hidden_files(tmp_path):
    mock_callback = MagicMock()
    handler = HotFolderHandler(mock_callback)
    
    class DummyEvent:
        def __init__(self, src_path):
            self.src_path = src_path
            
    test_path = str(tmp_path / ".DS_Store")
    handler.on_created(DummyEvent(test_path))
    
    import time
    time.sleep(0.1)
    
    mock_callback.assert_not_called()
