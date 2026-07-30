from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.rag.ingest import chunk_source
from app.rag.sources import KnowledgeSource

_SOURCE = KnowledgeSource(
    id="test-src",
    title="Test Source",
    url="https://example.com/doc.pdf",
    license="test",
)


def test_chunk_source_sizes_overlap_and_metadata() -> None:
    # No whitespace for the splitter to break on, so it must slice mid-text
    # and the overlap boundary is exact and easy to assert on.
    pages = ["X" * 130, "Y" * 60]
    splitter = RecursiveCharacterTextSplitter(chunk_size=50, chunk_overlap=10)

    chunks = chunk_source(_SOURCE, pages, splitter)

    assert all(len(chunk["text"]) <= 50 for chunk in chunks)

    page_1_chunks = [chunk for chunk in chunks if chunk["page"] == 1]
    page_2_chunks = [chunk for chunk in chunks if chunk["page"] == 2]
    assert len(page_1_chunks) == 3
    assert len(page_2_chunks) == 2

    # last 10 chars of a chunk overlap with the first 10 chars of the next one
    assert page_1_chunks[0]["text"][-10:] == page_1_chunks[1]["text"][:10]

    for chunk in chunks:
        assert chunk["source_id"] == "test-src"
        assert chunk["title"] == "Test Source"

    # chunk_index runs across the whole source, it does not reset per page
    assert [chunk["chunk_index"] for chunk in chunks] == list(range(len(chunks)))


def test_chunk_source_skips_blank_pages() -> None:
    pages = ["   \n  ", "real content " * 5]
    splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=150)

    chunks = chunk_source(_SOURCE, pages, splitter)

    assert len(chunks) > 0
    assert all(chunk["page"] == 2 for chunk in chunks)
