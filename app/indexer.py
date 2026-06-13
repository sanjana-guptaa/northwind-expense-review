"""
Policy indexer — run once before starting the API:
    python -m app.indexer
"""
import os
import re
import asyncio
import logging
from pathlib import Path

import fitz  # PyMuPDF
from sentence_transformers import SentenceTransformer
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import init_db, AsyncSessionLocal
from app.models import PolicyChunk

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

POLICIES_DIR = Path(os.getenv("POLICIES_DIR", "./policies"))
CHUNK_SIZE = 400        # tokens (approx chars/4)
CHUNK_OVERLAP = 50
EMBEDDING_MODEL = "BAAI/bge-small-en-v1.5"

HEADING_PATTERNS = [
    re.compile(r"^§\s*[\d][\d.]*", re.MULTILINE),
    re.compile(r"^\d+\.\d[\d.]*\s+\w", re.MULTILINE),
    re.compile(r"^[A-Z][A-Z\s]{5,}$", re.MULTILINE),
]

_embedder: SentenceTransformer | None = None


def get_embedder() -> SentenceTransformer:
    global _embedder
    if _embedder is None:
        log.info("Loading embedding model %s …", EMBEDDING_MODEL)
        _embedder = SentenceTransformer(EMBEDDING_MODEL)
    return _embedder


def extract_pages(pdf_path: Path) -> list[tuple[int, str]]:
    doc = fitz.open(str(pdf_path))
    pages = []
    for page_num in range(len(doc)):
        text = doc[page_num].get_text("text")
        pages.append((page_num + 1, text))
    doc.close()
    return pages


def detect_headings(text: str) -> list[int]:
    """Return sorted list of character offsets where headings start."""
    offsets = set()
    for pattern in HEADING_PATTERNS:
        for m in pattern.finditer(text):
            offsets.add(m.start())
    return sorted(offsets)


def heading_label(text: str, offset: int) -> str:
    line_end = text.find("\n", offset)
    return text[offset: line_end if line_end != -1 else offset + 80].strip()


def chunk_text(full_text: str) -> list[tuple[str, str]]:
    """Return list of (section_label, chunk_text)."""
    headings = detect_headings(full_text)

    if not headings:
        # Fallback: fixed-size chunks, no section labels
        log.warning("No headings found — using fixed-size chunking")
        words = full_text.split()
        chunks = []
        step = max(1, CHUNK_SIZE - CHUNK_OVERLAP)
        for i in range(0, len(words), step):
            chunk = " ".join(words[i: i + CHUNK_SIZE])
            chunks.append(("§unknown", chunk))
        return chunks

    # Build section boundaries
    boundaries = headings + [len(full_text)]
    chunks = []
    for i, start in enumerate(headings):
        label = heading_label(full_text, start)
        section_text = full_text[start: boundaries[i + 1]]
        words = section_text.split()

        if len(words) <= CHUNK_SIZE:
            chunks.append((label, section_text.strip()))
        else:
            step = max(1, CHUNK_SIZE - CHUNK_OVERLAP)
            for j in range(0, len(words), step):
                chunk = " ".join(words[j: j + CHUNK_SIZE])
                chunks.append((label, f"{label}\n{chunk}"))

    return chunks


async def index_policy(session: AsyncSession, pdf_path: Path, embedder: SentenceTransformer):
    doc_id = pdf_path.stem  # e.g. "policy1"

    existing = await session.scalar(
        select(PolicyChunk).where(PolicyChunk.doc_id == doc_id).limit(1)
    )
    if existing:
        log.info("  %s already indexed — skipping", doc_id)
        return 0

    log.info("  Indexing %s …", pdf_path.name)
    pages = extract_pages(pdf_path)
    full_text = "\n".join(text for _, text in pages)

    page_map: dict[int, int] = {}
    offset = 0
    for page_num, page_text in pages:
        page_map[offset] = page_num
        offset += len(page_text) + 1

    section_chunks = chunk_text(full_text)
    log.info("  %s: %d chunks from %d pages", doc_id, len(section_chunks), len(pages))

    texts = [chunk for _, chunk in section_chunks]
    embeddings = embedder.encode(texts, batch_size=32, show_progress_bar=False)

    chunk_objects = []
    for idx, ((section, chunk), embedding) in enumerate(zip(section_chunks, embeddings)):
        chunk_objects.append(PolicyChunk(
            doc_id=doc_id,
            section=section[:100],
            page=pages[min(idx, len(pages) - 1)][0],
            text=chunk,
            embedding=embedding.tolist(),
        ))

    session.add_all(chunk_objects)
    await session.flush()

    # Build ts_vector for BM25
    await session.execute(text(
        "UPDATE policy_chunks SET ts_vec = to_tsvector('english', text) "
        "WHERE doc_id = :doc_id AND ts_vec IS NULL"
    ), {"doc_id": doc_id})

    await session.commit()
    return len(chunk_objects)


async def run_indexer():
    await init_db()

    pdf_files = sorted(POLICIES_DIR.glob("*.pdf"))
    if not pdf_files:
        log.error("No PDF files found in %s", POLICIES_DIR)
        return

    log.info("Found %d policy PDFs", len(pdf_files))
    embedder = get_embedder()

    async with AsyncSessionLocal() as session:
        total = 0
        for pdf_path in pdf_files:
            n = await index_policy(session, pdf_path, embedder)
            total += n

    log.info("Indexing complete. %d new chunks inserted.", total)


if __name__ == "__main__":
    asyncio.run(run_indexer())
