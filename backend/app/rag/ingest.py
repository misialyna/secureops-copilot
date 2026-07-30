"""Build the local Qdrant knowledge-base index from the sources in sources.py.

Run from the repo root as:
    PYTHONPATH=backend uv run python -m app.rag.ingest
"""

import logging
import time
from pathlib import Path
from typing import Any

import fitz
import httpx
from langchain_text_splitters import RecursiveCharacterTextSplitter
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, PointStruct, VectorParams
from sentence_transformers import SentenceTransformer

from app.config import Settings
from app.rag.sources import KNOWLEDGE_SOURCES, KnowledgeSource

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

CHUNK_SIZE = 1000
CHUNK_OVERLAP = 150


def download_source(source: KnowledgeSource, raw_dir: Path) -> Path:
    raw_dir.mkdir(parents=True, exist_ok=True)
    dest = raw_dir / f"{source.id}.pdf"
    if dest.exists():
        logger.info("%s already downloaded at %s, skipping", source.id, dest)
        return dest

    logger.info("Downloading %s from %s", source.id, source.url)
    with httpx.stream("GET", source.url, follow_redirects=True, timeout=60.0) as response:
        response.raise_for_status()
        with dest.open("wb") as f:
            for chunk in response.iter_bytes():
                f.write(chunk)
    return dest


def extract_pages(pdf_path: Path) -> list[str]:
    with fitz.open(pdf_path) as doc:
        return [page.get_text() for page in doc]


def chunk_source(
    source: KnowledgeSource,
    pages: list[str],
    splitter: RecursiveCharacterTextSplitter,
) -> list[dict[str, Any]]:
    chunks: list[dict[str, Any]] = []
    chunk_index = 0
    for page_number, page_text in enumerate(pages, start=1):
        if not page_text.strip():
            continue
        for piece in splitter.split_text(page_text):
            chunks.append(
                {
                    "text": piece,
                    "source_id": source.id,
                    "title": source.title,
                    "page": page_number,
                    "chunk_index": chunk_index,
                }
            )
            chunk_index += 1
    return chunks


def build_index() -> None:
    settings = Settings()
    raw_dir = Path(settings.knowledge_raw_dir)
    splitter = RecursiveCharacterTextSplitter(chunk_size=CHUNK_SIZE, chunk_overlap=CHUNK_OVERLAP)

    start = time.monotonic()
    all_chunks: list[dict[str, Any]] = []
    total_pages = 0

    for source in KNOWLEDGE_SOURCES:
        pdf_path = download_source(source, raw_dir)
        pages = extract_pages(pdf_path)
        total_pages += len(pages)
        source_chunks = chunk_source(source, pages, splitter)
        all_chunks.extend(source_chunks)
        logger.info("%s: %d pages -> %d chunks", source.id, len(pages), len(source_chunks))

    logger.info("Loading embedding model %s", settings.embedding_model_name)
    model = SentenceTransformer(settings.embedding_model_name)

    logger.info("Encoding %d chunks", len(all_chunks))
    texts = [chunk["text"] for chunk in all_chunks]
    embeddings = model.encode(texts, show_progress_bar=True, normalize_embeddings=True)

    client = QdrantClient(path=settings.qdrant_path)
    vector_size = embeddings.shape[1]
    if client.collection_exists(settings.rag_collection_name):
        client.delete_collection(settings.rag_collection_name)
    client.create_collection(
        collection_name=settings.rag_collection_name,
        vectors_config=VectorParams(size=vector_size, distance=Distance.COSINE),
    )

    points = [
        PointStruct(id=i, vector=embeddings[i].tolist(), payload=all_chunks[i])
        for i in range(len(all_chunks))
    ]
    client.upsert(collection_name=settings.rag_collection_name, points=points)

    elapsed = time.monotonic() - start
    logger.info(
        "Ingest complete: %d pages, %d chunks, %.1fs",
        total_pages,
        len(all_chunks),
        elapsed,
    )


if __name__ == "__main__":
    build_index()
