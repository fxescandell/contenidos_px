import os
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    PROJECT_NAME: str = "WordPress Editorial Automation"
    API_V1_STR: str = "/api/v1"
    
    # Base paths
    SYNOLOGY_HOT_FOLDER: str = os.getenv("SYNOLOGY_HOT_FOLDER", "/tmp/hot_folder")
    WORKING_DIRECTORY: str = os.getenv("WORKING_DIRECTORY", "/tmp/working_dir")
    EXPORT_DIRECTORY: str = os.getenv("EXPORT_DIRECTORY", "/tmp/export_dir")
    
    # Database
    DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite:///./editorial.db")
    
    # Images
    IMAGE_MAX_WIDTH: int = 2000
    IMAGE_DEFAULT_QUALITY: int = 60
    
    # Telegram
    TELEGRAM_BOT_TOKEN: str | None = os.getenv("TELEGRAM_BOT_TOKEN")
    TELEGRAM_CHAT_ID: str | None = os.getenv("TELEGRAM_CHAT_ID")
    
    # Pipeline configurations
    ENABLE_AUTO_PUBLISH: bool = False

    class Config:
        env_file = ".env"
        case_sensitive = True

settings = Settings()
