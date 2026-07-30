import pytest
from pydantic import ValidationError

from app.rag.retriever import KnowledgeRetriever, RetrievedChunk
from app.rag.sources import KNOWLEDGE_SOURCES


def test_retrieved_chunk_valid() -> None:
    chunk = RetrievedChunk(
        text="some excerpt",
        source_id="nist-sp-800-61r3",
        title="Some Title",
        page=5,
        score=0.83,
    )
    assert chunk.page == 5
    assert chunk.score == pytest.approx(0.83)


def test_retrieved_chunk_requires_all_fields() -> None:
    with pytest.raises(ValidationError):
        RetrievedChunk(text="x", source_id="y", title="z")  # missing page/score


@pytest.mark.slow
def test_search_returns_relevant_chunks() -> None:
    retriever = KnowledgeRetriever()
    results = retriever.search("ransomware containment steps", top_k=5)

    assert len(results) > 0
    valid_source_ids = {source.id for source in KNOWLEDGE_SOURCES}
    for chunk in results:
        assert chunk.source_id in valid_source_ids
        assert chunk.page >= 1
        assert chunk.text.strip()
        assert -1.0 <= chunk.score <= 1.0
