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
