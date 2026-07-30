from functools import lru_cache

from pydantic import BaseModel
from qdrant_client import QdrantClient
from sentence_transformers import SentenceTransformer

from app.config import Settings


class RetrievedChunk(BaseModel):
    text: str
    source_id: str
    title: str
    page: int
    score: float


@lru_cache(maxsize=1)
def _get_embedding_model(model_name: str) -> SentenceTransformer:
    return SentenceTransformer(model_name)


class KnowledgeRetriever:
    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or Settings()
        self._client = QdrantClient(path=self._settings.qdrant_path)

    def search(self, query: str, top_k: int = 5) -> list[RetrievedChunk]:
        model = _get_embedding_model(self._settings.embedding_model_name)
        query_vector = model.encode(query, normalize_embeddings=True).tolist()

        results = self._client.query_points(
            collection_name=self._settings.rag_collection_name,
            query=query_vector,
            limit=top_k,
        )

        return [
            RetrievedChunk(
                text=point.payload["text"],
                source_id=point.payload["source_id"],
                title=point.payload["title"],
                page=point.payload["page"],
                score=point.score,
            )
            for point in results.points
        ]


@lru_cache(maxsize=1)
def get_retriever() -> KnowledgeRetriever:
    return KnowledgeRetriever()
