from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Typed 12-factor settings. All values come from env vars / .env."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Core
    app_env: str = "dev"
    log_level: str = "INFO"

    # Postgres
    database_url: str = "postgresql+psycopg://pioneer:pioneer@localhost:5433/pioneer"

    # Qdrant
    qdrant_url: str = "http://localhost:6333"
    qdrant_api_key: str | None = None
    qdrant_collection: str = "pioneer_memories"

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # Auth
    jwt_secret: str = Field(default="change-me-in-prod-this-is-dev-only")
    jwt_algorithm: str = "HS256"
    jwt_expires_minutes: int = 60 * 24 * 30  # 30 days for dev convenience

    # Embeddings
    embedding_model: str = "BAAI/bge-small-en-v1.5"
    embedding_dim: int = 384

    # MCP
    mcp_api_key: str = "dev-mcp-key-change-me"

    # --- Phase 2 ---
    # Fernet key (urlsafe base64, 32 bytes). Generate with:
    #   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    fernet_key: str = "REPLACE_ME_WITH_A_REAL_FERNET_KEY_44CHARS=="

    # Notion OAuth (public integration)
    notion_client_id: str = ""
    notion_client_secret: str = ""
    notion_redirect_uri: str = "http://localhost:8001/connectors/notion/oauth/callback"
    notion_api_base: str = "https://api.notion.com/v1"
    notion_oauth_authorize: str = "https://api.notion.com/v1/oauth/authorize"
    notion_oauth_token: str = "https://api.notion.com/v1/oauth/token"

    # Where the backend should redirect users at the end of the OAuth dance.
    frontend_base: str = "http://localhost:3000"

    # Chunking
    chunk_target_tokens: int = 800
    chunk_overlap_tokens: int = 100

    # Worker
    arq_max_jobs: int = 4

    # --- Phase 3 ---
    # HMAC secret for the append-only audit log chain. Separate from
    # FERNET_KEY so different leak scenarios have different blast radii.
    # Generate with:
    #   python -c "import secrets; print(secrets.token_urlsafe(64))"
    audit_hmac_key: str = "REPLACE_ME_WITH_A_REAL_AUDIT_HMAC_KEY"

    # --- Phase 4 ---
    # LLM provider for grounded chat + automations.
    # groq | anthropic | openai | stub. `stub` produces a deterministic
    # templated answer; useful in dev when no API keys are configured.
    llm_provider: str = "stub"
    llm_model: str = "llama-3.3-70b-versatile"
    llm_max_tokens: int = 1024
    llm_temperature: float = 0.2
    anthropic_api_key: str = ""
    openai_api_key: str = ""

    # Groq (OpenAI-compatible). Comma-separated list of API keys. The
    # provider auto-rotates to the next key when one hits a rate limit.
    groq_api_keys: str = ""
    groq_base_url: str = "https://api.groq.com/openai/v1"

    # Retrieval budgets for the grounded prompt.
    chat_top_k: int = 6
    chat_context_char_budget: int = 12_000

    # Automations
    automations_inbound_provider: str = "stub"  # stub | linkedin | gmail (later)
    drafts_per_run_max: int = 25


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
