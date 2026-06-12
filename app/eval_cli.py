"""
Standalone eval CLI: python -m app.eval_cli expected_outcomes.json
"""
from __future__ import annotations
import asyncio
import json
import sys
from pathlib import Path

from app.database import AsyncSessionLocal
from app.eval import run_eval


async def main(path: str) -> None:
    expected = json.loads(Path(path).read_text(encoding="utf-8"))
    async with AsyncSessionLocal() as session:
        result = await run_eval(expected, session)

    out_path = Path("eval_results") / f"cli_{result['run_at'].replace(':', '-')[:19]}.json"
    out_path.parent.mkdir(exist_ok=True)
    out_path.write_text(json.dumps(result, indent=2))

    print(f"\n=== Eval results written to {out_path} ===")
    print(f"Overall accuracy:     {result['verdict_accuracy_overall']:.0%}")
    print(f"Line item accuracy:   {result['verdict_accuracy_line_items']:.0%}")
    print(f"Citation precision:   {result['citation_precision']:.0%}")
    print(f"Citation recall:      {result['citation_recall']:.0%}")
    print(f"Retrieval hit@5:      {result['retrieval_hit_at_5']:.0%}")
    refusal = result.get("refusal_rate")
    if refusal is not None:
        print(f"Refusal rate:         {refusal:.0%}")
    print(f"ECE:                  {result['ece']:.4f}")
    print()
    for b in result.get("bucketed_accuracy", []):
        print(
            f"  [{b['bucket']}]  n={b['count']}  "
            f"mean_conf={b['mean_confidence']:.2f}  acc={b['accuracy']:.2f}  "
            f"cal_err={b['calibration_error']:.3f}"
        )


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python -m app.eval_cli expected_outcomes.json")
        sys.exit(1)
    asyncio.run(main(sys.argv[1]))
