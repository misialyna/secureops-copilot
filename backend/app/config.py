from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    groq_api_key: str = ""
    database_url: str = ""
    app_version: str = "0.1.0"

    knowledge_raw_dir: str = "knowledge/raw"
    qdrant_path: str = "data/qdrant"
    rag_collection_name: str = "knowledge_base"
    embedding_model_name: str = "BAAI/bge-m3"

    groq_model_name: str = "llama-3.3-70b-versatile"
    checkpoint_db_path: str = "data/checkpoints.sqlite"
    groq_max_retries: int = 3
    groq_retry_backoff_seconds: float = 1.0

    attack_stix_url: str = (
        "https://raw.githubusercontent.com/mitre-attack/attack-stix-data/"
        "master/enterprise-attack/enterprise-attack.json"
    )
    attack_stix_path: str = "knowledge/raw/enterprise-attack.json"

    evidence_dir: str = "data/evidence"
    max_evidence_file_size_mb: int = 50
