from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]
PROJECT_ROOT = BACKEND_DIR.parent


class Settings(BaseSettings):
    # Application
    app_name: str = "Credit Memo AI"
    app_env: str = "development"
    debug: bool = True

    # Database
    database_url: str

    # Storage
    upload_dir: Path = PROJECT_ROOT / "storage" / "uploads"
    extracted_dir: Path = PROJECT_ROOT / "storage" / "extracted"
    faiss_dir: Path = PROJECT_ROOT / "storage" / "faiss"
    generated_dir: Path = PROJECT_ROOT / "storage" / "generated"
    temp_dir: Path = PROJECT_ROOT / "storage" / "temp"

    # AI and retrieval
    faiss_index_name: str = "credit_documents"
    embedding_model: str = "text-embedding-005-cto-oth"
    embedding_batch_size: int = 48
    embedding_batch_token_limit: int = 16000
    embedding_api_key: str
    llm_model: str = "claude-sonnet-4-6-Dev"
    llm_api_key: str
    llm_base_url: str

    # Upload restrictions
    max_upload_size_mb: int = 50
    allowed_file_types: str = "application/pdf"

    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    def resolve_path(self, path: Path) -> Path:
        """Resolve relative paths from the backend directory."""
        if path.is_absolute():
            return path

        return (PROJECT_ROOT / path).resolve()

    def ensure_storage_directories(self) -> None:
        directories = [
            self.upload_dir,
            self.extracted_dir,
            self.faiss_dir,
            self.generated_dir,
            self.temp_dir,
        ]

        for directory in directories:
            self.resolve_path(directory).mkdir(
                parents=True,
                exist_ok=True,
            )

    def get_allowed_file_types(self) -> set[str]:
        """Convert comma-separated MIME types into a set."""
        return {
            file_type.strip()
            for file_type in self.allowed_file_types.split(",")
            if file_type.strip()
        }


@lru_cache
def get_settings() -> Settings:
    configured_settings = Settings()
    configured_settings.ensure_storage_directories()
    return configured_settings


settings = get_settings()
