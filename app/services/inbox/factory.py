from typing import Optional

from app.schemas.inbox import InboxConnectionSettings
from app.core.inbox_enums import InboxMode
from app.services.inbox.clients.base import BaseRemoteInboxClient
from app.services.inbox.clients.local import LocalFolderInboxClient
from app.services.inbox.clients.ftp import FtpRemoteInboxClient
from app.services.inbox.clients.sftp import SftpRemoteInboxClient

class InboxClientFactory:
    @staticmethod
    def get_client(settings: InboxConnectionSettings) -> Optional[BaseRemoteInboxClient]:
        if settings.mode == InboxMode.LOCAL:
            return LocalFolderInboxClient(settings)
        elif settings.mode == InboxMode.FTP:
            return FtpRemoteInboxClient(settings)
        elif settings.mode == InboxMode.SFTP:
            return SftpRemoteInboxClient(settings)
        return None
