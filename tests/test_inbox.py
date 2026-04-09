import pytest
from app.schemas.inbox import InboxConnectionSettings
from app.core.inbox_enums import InboxMode
from app.services.inbox.validators import InboxSettingsValidator
from app.services.inbox.factory import InboxClientFactory
from app.services.inbox.clients.local import LocalFolderInboxClient
from app.services.inbox.clients.ftp import FtpRemoteInboxClient

def test_inbox_validator_local_empty():
    settings = InboxConnectionSettings(mode=InboxMode.LOCAL, local_path="")
    valid, errors = InboxSettingsValidator.validate(settings)
    assert not valid
    assert "La ruta local es obligatoria" in errors[0]

def test_inbox_validator_ftp_missing_auth():
    settings = InboxConnectionSettings(mode=InboxMode.FTP, host="ftp.example.com", username="user")
    valid, errors = InboxSettingsValidator.validate(settings)
    assert not valid
    assert "La contraseña es obligatoria" in errors[0]

def test_inbox_validator_move_and_delete_conflict():
    settings = InboxConnectionSettings(
        mode=InboxMode.LOCAL, 
        local_path="/tmp", 
        delete_after_import=True, 
        move_after_import=True
    )
    valid, errors = InboxSettingsValidator.validate(settings)
    assert not valid
    assert any("mover y borrar a la vez" in e for e in errors)

def test_factory_returns_correct_client():
    settings_local = InboxConnectionSettings(mode=InboxMode.LOCAL, local_path="/tmp")
    client = InboxClientFactory.get_client(settings_local)
    assert isinstance(client, LocalFolderInboxClient)
    
    settings_ftp = InboxConnectionSettings(mode=InboxMode.FTP, host="ftp", username="u", password="p")
    client = InboxClientFactory.get_client(settings_ftp)
    assert isinstance(client, FtpRemoteInboxClient)

def test_local_client_list_entries(tmp_path):
    # Setup
    hot_folder = tmp_path / "hot"
    hot_folder.mkdir()
    (hot_folder / "test.pdf").write_text("dummy")
    (hot_folder / ".hidden").write_text("hidden")
    (hot_folder / "batch1").mkdir()
    
    settings = InboxConnectionSettings(mode=InboxMode.LOCAL, local_path=str(hot_folder))
    client = LocalFolderInboxClient(settings)
    
    res = client.list_entries()
    assert res.success
    names = [e.name for e in res.entries]
    
    # Should see test.pdf and batch1
    assert "test.pdf" in names
    assert "batch1" in names
    # Should ignore .hidden
    assert ".hidden" not in names

def test_local_client_path_traversal_protection(tmp_path):
    hot_folder = tmp_path / "hot"
    hot_folder.mkdir()
    
    settings = InboxConnectionSettings(mode=InboxMode.LOCAL, local_path=str(hot_folder))
    client = LocalFolderInboxClient(settings)
    
    # Intento de salir de la carpeta configurada
    res = client.list_entries("../../../etc")
    assert not res.success
    assert "Ruta inválida" in res.message
