from enum import Enum

class SettingType(str, Enum):
    STRING = "string"
    INTEGER = "integer"
    FLOAT = "float"
    BOOLEAN = "boolean"
    JSON = "json"

class HotFolderMode(str, Enum):
    LOCAL = "local"
    FTP = "ftp"
    SFTP = "sftp"
    DISABLED = "disabled"

class ExportMode(str, Enum):
    PER_ARTICLE = "per_article"
    PER_BATCH = "per_batch"

class OcrEngine(str, Enum):
    TESSERACT = "tesseract"
    PADDLEOCR = "paddleocr"
    AZURE_VISION = "azure_vision"
    DISABLED = "disabled"

class LlmProvider(str, Enum):
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    AZURE = "azure"
    OLLAMA = "ollama"
    GROQ = "groq"
    MISTRAL = "mistral"
    GEMINI = "gemini"
