from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Enterprise AI Copilot"
    app_version: str = "0.4.0"

    deepseek_api_key: str = Field(default="", alias="DEEPSEEK_API_KEY")
    deepseek_base_url: str = Field(
        default="https://api.deepseek.com",
        alias="DEEPSEEK_BASE_URL",
    )
    deepseek_model: str = Field(default="deepseek-chat", alias="DEEPSEEK_MODEL")
    frontend_origin: str = Field(
        default="http://localhost:5173",
        alias="FRONTEND_ORIGIN",
    )
    max_revision_count: int = Field(
        default=2,
        ge=0,
        alias="MAX_REVISION_COUNT",
    )
    max_tool_iterations: int = Field(
        default=4,
        ge=0,
        alias="MAX_TOOL_ITERATIONS",
    )
    knowledge_top_k: int = Field(default=3, ge=1, alias="KNOWLEDGE_TOP_K")
    knowledge_min_score: float = Field(
        default=0.5,
        ge=-1.0,
        le=1.0,
        alias="KNOWLEDGE_MIN_SCORE",
    )
    embedding_model: str = Field(
        default="BAAI/bge-small-zh-v1.5",
        alias="EMBEDDING_MODEL",
    )

    @property
    def backend_dir(self) -> Path:
        return Path(__file__).resolve().parents[2]

    @property
    def knowledge_base_dir(self) -> Path:
        return self.backend_dir / "knowledge_base"

    @property
    def knowledge_index_path(self) -> Path:
        return self.backend_dir / "data" / "knowledge_index.json"

    @property
    def database_path(self) -> Path:
        return self.backend_dir / "data" / "enterprise_ai_copilot.db"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
