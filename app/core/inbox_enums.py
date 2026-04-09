from enum import Enum

class InboxMode(str, Enum):
    LOCAL = "local"
    FTP = "ftp"
    SFTP = "sftp"
    DISABLED = "disabled"

class ProcessedEntryAction(str, Enum):
    NONE = "none"
    MOVE = "move"
    DELETE = "delete"
