"""
Policy Q&A via RAG — grounded, cited answers with out-of-scope refusal.
"""
from __future__ import annotations
import os
import anthropic
from dotenv import load_dotenv
load_dotenv(override=True)

from sqlalchemy.ext.asyncio import AsyncSession
from app.retriever import retrieve, build_chunk_text_map

_SYSTEM = """You are a policy assistant for Northwind Logistics expense and travel policies.

Rules — follow without exception:

1. CONTEXT ONLY: Answer solely from the policy excerpts provided below. Do NOT use outside knowledge.
2. OUT-OF-SCOPE: If the question has nothing to do with expense, travel, or Northwind Logistics policy,
   set is_out_of_scope=true and answer="This question is outside the expense and travel policy scope."
3. INSUFFICIENT CONTEXT: If the excerpts do not contain enough detail to answer fully, say so explicitly.
4. CITATIONS REQUIRED: Include exact verbatim short phrases (5-20 words) copied from the excerpts.
5. CONCISE: Answer in 1-3 clear sentences. Lead with the direct answer, then support with citations."""

_ANSWER_TOOL = {
    "name": "policy_answer",
    "description": "Return a grounded answer to a policy question with citations",
    "input_schema": {
        "type": "object",
        "properties": {
            "answer": {"type": "string"},
            "is_out_of_scope": {"type": "boolean"},
            "citations": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "doc_id": {"type": "string"},
                        "section": {"type": "string"},
                        "page": {"type": "integer"},
                        "exact_quote": {"type": "string"},
                    },
                    "required": ["doc_id", "section", "page", "exact_quote"],
                },
            },
        },
        "required": ["answer", "is_out_of_scope", "citations"],
    },
}


async def answer_question(question: str, session: AsyncSession) -> dict:
    anth = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    chunks = await retrieve(question, session, top_k=6)

    if not chunks:
        return {
            "answer": "No relevant policy content found for this question.",
            "is_out_of_scope": False,
            "citations": [],
            "retrieved_chunks": [],
        }

    context = "\n\n".join(
        f"[{c.doc_id} | {c.section} | page {c.page}]\n{c.text}"
        for c in chunks
    )

    response = anth.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1024,
        system=_SYSTEM,
        tools=[_ANSWER_TOOL],
        tool_choice={"type": "tool", "name": "policy_answer"},
        messages=[{
            "role": "user",
            "content": f"Policy excerpts:\n\n{context}\n\n---\n\nQuestion: {question}",
        }],
    )

    raw: dict = {}
    for block in response.content:
        if block.type == "tool_use" and block.name == "policy_answer":
            raw = block.input
            break

    if not raw:
        return {
            "answer": "Unable to generate an answer.",
            "is_out_of_scope": False,
            "citations": [],
            "retrieved_chunks": [],
        }

    # Validate citations: only keep quotes actually present in retrieved text
    chunk_text_map = build_chunk_text_map(chunks)
    all_text = " ".join(chunk_text_map.values())
    norm_all = " ".join(all_text.split()).lower()

    valid_citations = []
    for c in raw.get("citations", []):
        quote = c.get("exact_quote", "")
        norm_quote = " ".join(quote.split()).lower()
        if norm_quote and norm_quote in norm_all:
            valid_citations.append(c)

    return {
        "answer": raw.get("answer", ""),
        "is_out_of_scope": raw.get("is_out_of_scope", False),
        "citations": valid_citations,
        "retrieved_chunks": [
            {
                "doc_id": c.doc_id,
                "section": c.section,
                "page": c.page,
                "score": round(c.rrf_score, 5),
            }
            for c in chunks
        ],
    }
