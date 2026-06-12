"""
Evaluation harness: accuracy, citation precision/recall, retrieval hit@5, ECE.
"""
from __future__ import annotations
import json
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Submission, Verdict
from app.retriever import retrieve
from app.schemas import EvalExpectedOutcome

RESULTS_DIR = Path("./eval_results")
CONFIDENCE_BUCKETS = [(0.0, 0.5), (0.5, 0.7), (0.7, 0.9), (0.9, 1.01)]
BUCKET_LABELS = ["0.0–0.5", "0.5–0.7", "0.7–0.9", "0.9–1.0"]


async def run_eval(expected_list: list[dict], session: AsyncSession) -> dict:
    from app.chat import answer_question

    outcomes = [EvalExpectedOutcome(**e) for e in expected_list]

    per_submission = []
    overall_correct = []
    line_item_correct = []
    citation_precision_vals = []
    citation_recall_vals = []
    hit5_vals = []
    confidence_correctness_pairs: list[tuple[float, bool]] = []
    refusal_results: list[bool] = []

    for expected in outcomes:
        sub = await session.scalar(
            select(Submission).where(Submission.folder_name == expected.submission_id)
        )
        if not sub:
            continue

        verdict_row = await session.scalar(
            select(Verdict)
            .where(Verdict.submission_id == sub.id)
            .order_by(Verdict.created_at.desc())
            .limit(1)
        )
        if not verdict_row:
            continue

        verdict_data = verdict_row.verdict_json

        # Overall verdict accuracy
        overall_match = verdict_data["overall"] == expected.expected_overall
        overall_correct.append(overall_match)
        confidence_correctness_pairs.append((verdict_data["confidence"], overall_match))

        # Line item accuracy
        actual_items = {item["receipt_file"]: item["verdict"] for item in verdict_data.get("line_items", [])}
        for exp_item in expected.expected_line_items:
            match = actual_items.get(exp_item.receipt_file) == exp_item.verdict
            line_item_correct.append(match)

        # Citation precision + recall
        for exp_citation in expected.expected_citations:
            actual_line = next(
                (item for item in verdict_data.get("line_items", [])
                 if item["receipt_file"] == exp_citation.receipt_file),
                None
            )
            if actual_line:
                returned_sections = {c["section"] for c in actual_line.get("policy_citations", [])}
                precision = 1.0 if exp_citation.section in returned_sections else 0.0
                recall = 1.0 if exp_citation.section in returned_sections else 0.0
                citation_precision_vals.append(precision)
                citation_recall_vals.append(recall)

                # Retrieval hit@5
                query = f"{actual_line.get('category', '')} {actual_line.get('amount', '')} grade {sub.employee_json.get('grade', '')}"
                chunks = await retrieve(query, session, top_k=5)
                hit = any(exp_citation.section in c.section for c in chunks)
                hit5_vals.append(1.0 if hit else 0.0)

        # Out-of-scope refusal rate
        for query in expected.out_of_scope_queries:
            try:
                resp = await answer_question(query, session)
                refusal_results.append(resp.get("is_out_of_scope", False))
            except Exception:
                refusal_results.append(False)

        per_submission.append({
            "submission_id": expected.submission_id,
            "expected_overall": expected.expected_overall,
            "actual_overall": verdict_data["overall"],
            "overall_correct": overall_match,
            "confidence": verdict_data["confidence"],
        })

    # Aggregate metrics
    verdict_accuracy_overall = _mean(overall_correct)
    verdict_accuracy_line = _mean(line_item_correct)
    citation_precision = _mean(citation_precision_vals)
    citation_recall = _mean(citation_recall_vals)
    retrieval_hit5 = _mean(hit5_vals)
    refusal_rate = _mean([float(r) for r in refusal_results]) if refusal_results else None

    # ECE + bucketed accuracy
    bucketed, ece = _calibration(confidence_correctness_pairs)

    result = {
        "run_at": datetime.now(timezone.utc).isoformat(),
        "verdict_accuracy_overall": round(verdict_accuracy_overall, 4),
        "verdict_accuracy_line_items": round(verdict_accuracy_line, 4),
        "citation_precision": round(citation_precision, 4),
        "citation_recall": round(citation_recall, 4),
        "retrieval_hit_at_5": round(retrieval_hit5, 4),
        "refusal_rate": round(refusal_rate, 4) if refusal_rate is not None else None,
        "ece": round(ece, 4),
        "bucketed_accuracy": bucketed,
        "per_submission": per_submission,
    }

    RESULTS_DIR.mkdir(exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d-%H-%M")
    (RESULTS_DIR / f"{ts}.json").write_text(json.dumps(result, indent=2))

    return result


def _mean(vals: list) -> float:
    return sum(vals) / len(vals) if vals else 0.0


def _calibration(pairs: list[tuple[float, bool]]) -> tuple[list[dict], float]:
    buckets_data = []
    total_n = len(pairs)
    ece = 0.0

    for (lo, hi), label in zip(CONFIDENCE_BUCKETS, BUCKET_LABELS):
        bucket = [(conf, correct) for conf, correct in pairs if lo <= conf < hi]
        n = len(bucket)
        if n == 0:
            buckets_data.append({
                "bucket": label, "count": 0,
                "mean_confidence": 0.0, "accuracy": 0.0, "calibration_error": 0.0,
            })
            continue
        mean_conf = _mean([c for c, _ in bucket])
        accuracy = _mean([float(correct) for _, correct in bucket])
        cal_error = abs(mean_conf - accuracy)
        ece += (n / max(total_n, 1)) * cal_error
        buckets_data.append({
            "bucket": label,
            "count": n,
            "mean_confidence": round(mean_conf, 4),
            "accuracy": round(accuracy, 4),
            "calibration_error": round(cal_error, 4),
        })

    return buckets_data, ece
