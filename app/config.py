"""全局配置：统一从环境变量（.env）读取，敏感信息不落代码。"""
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(BASE_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # 应用
    app_name: str = "仁心医院患者服务工单 Agent"
    app_env: str = "dev"
    host: str = "0.0.0.0"
    port: int = 8000
    debug: bool = True

    # 鉴权
    jwt_secret: str = "dev-only-secret-please-change"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 720

    # 大模型
    llm_api_key: str = ""
    llm_base_url: str = ""
    llm_model: str = "deepseek-chat"
    llm_temperature: float = 0.2
    llm_timeout: int = 60

    embedding_api_key: str = ""
    embedding_base_url: str = ""
    embedding_model: str = "BAAI/bge-m3"
    embedding_dim: int = 1024

    # 数据库
    database_url: str = "sqlite+aiosqlite:///./data/hospital.db"

    # Redis
    redis_url: str = "redis://127.0.0.1:6379/0"
    redis_enabled: bool = True
    faq_cache_ttl: int = 7 * 24 * 3600
    session_ttl: int = 2 * 3600
    ticket_cache_ttl: int = 60

    # RAG
    knowledge_dir: str = "./data/knowledge"
    rag_top_k: int = 5
    rag_candidate_k: int = 12
    rag_min_score: float = 0.18

    milvus_uri: str = ""
    milvus_token: str = ""
    milvus_collection: str = "hospital_knowledge"

    es_url: str = ""
    es_username: str = ""
    es_password: str = ""
    es_index: str = "hospital_knowledge"

    rerank_api_url: str = ""
    rerank_api_key: str = ""
    rerank_model: str = "BAAI/bge-reranker-v2-m3"

    # MCP
    mcp_mode: str = "local"  # local | client
    mcp_server_command: str = "python"
    mcp_server_args: str = "-m app.mcp.server"
    mcp_timeout_seconds: int = 30

    # 业务规则
    cancel_min_hours: int = 2
    fee_dispute_amount: float = 300.0

    @property
    def llm_enabled(self) -> bool:
        return bool(self.llm_api_key and self.llm_model)

    @property
    def embedding_enabled(self) -> bool:
        return bool(self.embedding_api_key and self.embedding_base_url)

    @property
    def knowledge_path(self) -> Path:
        p = Path(self.knowledge_dir)
        return p if p.is_absolute() else (BASE_DIR / p).resolve()

    @property
    def database_is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
