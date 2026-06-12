"""
Hybrid retriever: BGE dense (pgvector) + BM25 (PostgreSQL full-text), fused via RRF.
"""
from __future__ import annotations
import os
from dataclasses import dataclass

from sentence_transformers import SentenceTransformer
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.indexer import get_embedder

RRF_K = 60
TOP_N = 20
TOP_FINAL = 5


@dataclass
class RetrievedChunk:
    chunk_id: str
    doc_id: str
    section: str
    page: int
    text: str
    rrf_score: float


async def retrieve(query: str, session: AsyncSession, top_k: int = TOP_FINAL) -> list[RetrievedChunk]:
    embedder = get_embedder()
    query_vec = embedder.encode(query).tolist()

    # Dense search via pgvector
    dense_rows = await session.execute(
        text("""
            SELECT id::text, doc_id, section, page, text,
                   row_number() OVER (ORDER BY embedding <=> cast(:vec AS vector)) AS rank
            FROM policy_chunks
            ORDER BY embedding <=> cast(:vec AS vector)
            LIMIT :n
        """),
        {"vec": str(query_vec), "n": TOP_N},
    )
    dense = {row.id: (row, int(row.rank)) for row in dense_rows}

    # BM25 via PostgreSQL full-text
    bm25_rows = await session.execute(
        text("""
            SELECT id::text, doc_id, section, page, text,
                   row_number() OVER (ORDER BY ts_rank(ts_vec, query) DESC) AS rank
            FROM policy_chunks, plainto_tsquery('english', :q) query
            WHERE ts_vec @@ query
            ORDER BY ts_rank(ts_vec, query) DESC
            LIMIT :n
        """),
        {"q": query, "n": TOP_N},
    )
    bm25 = {row.id: (row, int(row.rank)) for row in bm25_rows}

    # RRF fusion
    all_ids = set(dense) | set(bm25)
    scored: list[tuple[float, str]] = []
    for chunk_id in all_ids:
        rank_d = dense[chunk_id][1] if chunk_id in dense else TOP_N + 1
        rank_b = bm25[chunk_id][1] if chunk_id in bm25 else TOP_N + 1
        score = 1.0 / (RRF_K + rank_d) + 1.0 / (RRF_K + rank_b)
        scored.append((score, chunk_id))

    scored.sort(reverse=True)
    top_ids = [chunk_id for _, chunk_id in scored[:top_k]]

    # Build result preserving order
    source = {**{cid: row for cid, (row, _) in dense.items()},
               **{cid: row for cid, (row, _) in bm25.items()}}

    results = []
    for chunk_id in top_ids:
        row = source[chunk_id]
        rrf_score = next(s for s, cid in scored if cid == chunk_id)
        results.append(RetrievedChunk(
            chunk_id=chunk_id,
            doc_id=row.doc_id,
            section=row.section,
            page=row.page,
            text=row.text,
            rrf_score=rrf_score,
        ))

    return results


def build_chunk_text_map(chunks: list[RetrievedChunk]) -> dict[str, str]:
    """Key: doc_id + section → text. Used for citation validation."""
    return {f"{c.doc_id}:{c.section}": c.text for c in chunks}
