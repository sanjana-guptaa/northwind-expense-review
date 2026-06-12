"""
Verdict engine — Sonnet 4.6 with strict prompt contract.
Citation validation enforced in code after generation.
"""
from __future__ import annotations
import json
import os

from dotenv import load_dotenv
load_dotenv(override=True)

import anthropic
from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas import Citation, LineItemVerdict, ReceiptData, SubmissionVerdict
from app.retriever import RetrievedChunk, retrieve, build_chunk_text_map

SYSTEM_PROMPT = """You are a compliance reviewer for Northwind Logistics expense policy.

Rules — follow without exception:

1. CONTEXT ONLY: Base every verdict solely on the policy excerpts provided below.
   If the context does not contain sufficient information to make a determination,
   set verdict="flagged" and note "Insufficient policy context" in reasoning.
   Do NOT infer or hallucinate policy rules not present in the excerpts.

2. CITATIONS REQUIRED: You MUST include at least one citation per line item.
   Copy a short phrase (5-20 words) directly from the policy excerpt text above.
   The exact_quote must appear word-for-word in the provided chunk text.
   Prefer short, specific phrases over long sentences.

3. CONFIDENCE CALIBRATION: confidence reflects how certain you are given the
   available evidence. Any material uncertainty → confidence < 0.7.
   A confident wrong answer is worse than an uncertain correct one.

4. OUTPUT: Return only valid JSON matching the schema. No prose outside the JSON."""

VERDICT_TOOL = {
    "name": "submit_verdict",
    "description": "Submit a structured compliance verdict for an expense submission",
    "input_schema": {
        "type": "object",
        "properties": {
            "overall": {
                "type": "string",
                "enum": ["compliant", "flagged", "rejected"],
                "description": "Overall verdict for the entire submission",
            },
            "total_amount": {"type": "number"},
            "approved_amount": {"type": "number"},
            "summary": {"type": "string"},
            "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
            "line_items": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "receipt_file": {"type": "string"},
                        "amount": {"type": "number"},
                        "category": {"type": "string"},
                        "verdict": {
                            "type": "string",
                            "enum": ["compliant", "flagged", "rejected"],
                        },
                        "reasoning": {"type": "string"},
                        "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
                        "policy_citations": {
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
                    "required": ["receipt_file", "amount", "category", "verdict", "reasoning", "confidence"],
                },
            },
        },
        "required": ["overall", "total_amount", "approved_amount", "summary", "confidence", "line_items"],
    },
}


def _build_context_block(
    employee: dict,
    receipts: list[tuple[str, ReceiptData]],
    chunks_per_receipt: dict[str, list[RetrievedChunk]],
) -> str:
    lines = ["=== EMPLOYEE ==="]
    for k, v in employee.items():
        lines.append(f"{k}: {v}")

    lines.append("\n=== POLICY EXCERPTS ===")
    seen_chunks: set[str] = set()
    for filename, _ in receipts:
        for chunk in chunks_per_receipt.get(filename, []):
            key = f"{chunk.doc_id}:{chunk.section}"
            if key not in seen_chunks:
                seen_chunks.add(key)
                lines.append(
                    f"\n[{chunk.doc_id} | {chunk.section} | page {chunk.page}]\n{chunk.text}"
                )

    lines.append("\n=== RECEIPTS ===")
    for filename, receipt in receipts:
        lines.append(f"\nFile: {filename}")
        lines.append(f"  Vendor: {receipt.vendor}")
        lines.append(f"  Date: {receipt.date}")
        lines.append(f"  Amount: {receipt.currency} {receipt.amount:.2f}")
        lines.append(f"  Category: {receipt.category}")
        lines.append(f"  Attendees: {', '.join(receipt.attendees) or 'none listed'}")
        lines.append(f"  Purpose: {receipt.business_purpose}")

    return "\n".join(lines)


def _normalize(text: str) -> str:
    return " ".join(text.split()).lower()


def _validate_citations(
    line_items: list[LineItemVerdict],
    chunk_text_map: dict[str, str],
) -> list[LineItemVerdict]:
    """Drop citations whose exact_quote is not found in any retrieved chunk."""
    all_chunks_text = " ".join(chunk_text_map.values())
    norm_all = _normalize(all_chunks_text)

    for item in line_items:
        valid = []
        for citation in item.policy_citations:
            if not citation.exact_quote:
                continue
            norm_quote = _normalize(citation.exact_quote)
            # Check specific chunk first, then fall back to all retrieved chunks
            key = f"{citation.doc_id}:{citation.section}"
            source = chunk_text_map.get(key, "")
            if norm_quote in _normalize(source) or norm_quote in norm_all:
                valid.append(citation)
        item.policy_citations = valid
    return line_items


def _determine_overall(line_items: list[LineItemVerdict]) -> str:
    verdicts = {item.verdict for item in line_items}
    if "rejected" in verdicts:
        return "rejected"
    if "flagged" in verdicts:
        return "flagged"
    return "compliant"


async def generate_verdict(
    submission_id: str,
    employee: dict,
    receipts: list[tuple[str, ReceiptData]],
    session: AsyncSession,
) -> SubmissionVerdict:
    anth = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

    # Retrieve policy chunks per receipt
    chunks_per_receipt: dict[str, list[RetrievedChunk]] = {}
    all_chunks: list[RetrievedChunk] = []
    for filename, receipt in receipts:
        query = (
            f"{receipt.category} {receipt.amount} {receipt.vendor} "
            f"grade {employee.get('grade', '')} {employee.get('trip_purpose', '')}"
        )
        chunks = await retrieve(query, session)
        chunks_per_receipt[filename] = chunks
        all_chunks.extend(chunks)

    chunk_text_map = build_chunk_text_map(all_chunks)
    context = _build_context_block(employee, receipts, chunks_per_receipt)

    response = anth.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=4096,
        system=SYSTEM_PROMPT,
        tools=[VERDICT_TOOL],
        tool_choice={"type": "tool", "name": "submit_verdict"},
        messages=[{
            "role": "user",
            "content": (
                f"Review this expense submission and return a verdict.\n\n{context}"
            ),
        }],
    )

    raw: dict = {}
    for block in response.content:
        if block.type == "tool_use" and block.name == "submit_verdict":
            raw = block.input
            break

    if not raw:
        raise ValueError("Sonnet did not return verdict tool use block")

    # Parse line items
    line_items = []
    for item_raw in raw.get("line_items", []):
        citations = [
            Citation(**c) for c in item_raw.get("policy_citations", [])
        ]
        line_items.append(LineItemVerdict(
            receipt_file=item_raw["receipt_file"],
            amount=item_raw["amount"],
            category=item_raw["category"],
            verdict=item_raw["verdict"],
            policy_citations=citations,
            reasoning=item_raw["reasoning"],
            confidence=item_raw["confidence"],
        ))

    # Enforce citation validity in code
    line_items = _validate_citations(line_items, chunk_text_map)

    # Recalculate overall from line items (don't trust LLM's overall if items disagree)
    overall = _determine_overall(line_items)

    return SubmissionVerdict(
        submission_id=submission_id,
        overall=overall,
        total_amount=raw.get("total_amount", sum(r.amount for _, r in receipts)),
        approved_amount=raw.get("approved_amount", 0.0),
        line_items=line_items,
        summary=raw.get("summary", ""),
        confidence=raw.get("confidence", 0.5),
    )
