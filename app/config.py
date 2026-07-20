from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    llm_model: str
    llm_base_url: str
    llm_api_key: str
    llm_timeout: int = 60
    llm_max_retries: int = 5

    # MySQL
    mysql_host: str = "localhost"
    mysql_port: int = 3306
    mysql_user: str = "root"
    mysql_password: str
    mysql_database: str
    mysql_pool_min: int = 1
    mysql_pool_max: int = 5

    #Tavily
    tavily_api_key: str

    # RAG
    embed_model: str
    chroma_dir: Path = Path("data/chroma")
    rag_chunk_size: int = 800
    rag_chunk_overlap: int = 120

    # 运行
    data_dir: Path = Path("data")
    checkpoint_db: Path = Path("data/checkpoints.sqlite")
    max_concurrent_tasks: int = 5
    event_queue_maxsize: int = 1000

    # 安全
    cors_origins: list[str] = ["http://localhost:3000"]
    api_token: str | None = None
    sql_table_allowlist: list[str] = []
    sql_row_limit: int = 100


@lru_cache
def get_settings() -> Settings:
    return Settings()
