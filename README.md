# Northwind Logistics — AI Expense Review

An AI-powered expense review system for Northwind Logistics. Reviewers submit employee expense receipts (PDF, JPEG/PNG, plain text), and the system extracts structured fields, retrieves relevant policy excerpts via hybrid RAG, and generates grounded compliance verdicts with verbatim citations.

---

## Quick Start

### Prerequisites

- Docker Desktop running
- Python 3.11+
- Anthropic API key

### 1. Start the database

```bash
docker compose up -d db
```

### 2. Set environment variables

Create `.env` in the project root:

```
ANTHROPIC_API_KEY=sk-ant-...
DATABASE_URL=postgresql+asyncpg://northwind:northwind@localhost:5432/northwind
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Index policies

```bash
python -m app.indexer
```

Expected output: ~627 chunks from 8 PDFs.

> **Docker users:** If running via `docker compose up`, index policies inside the container after first start:
> ```bash
> docker compose exec api python -m app.indexer
> ```

### 5. Start the API

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

On startup, the five employees from the provided JSON files are automatically seeded into the database.

### 6. Start the UI

```bash
python -m streamlit run ui/streamlit_app.py --server.port 8501
```

Open [http://localhost:8501](http://localhost:8501).

---

## Architecture

```
Browser (Streamlit UI)
        │
        ▼
FastAPI REST API (port 8000)
   ├── /api/employees          ← employee CRUD + startup seeding
   ├── /api/submissions/*      ← ingest from disk or browser upload
   ├── /api/submissions/{id}/analyze
   ├── /api/overrides          ← append-only override audit trail
   ├── /api/chat               ← policy Q&A (RAG + Sonnet)
   └── /api/eval               ← evaluation harness
        │
        ├── Extractor (app/extractor.py)
        │     └── Sonnet 4.6 with tool_use extract_receipt
        │          ├── text path: PDF-text or .txt → text call
        │          └── image path: .jpg/.png or scanned PDF → vision call
        │
        ├── Retriever (app/retriever.py)
        │     └── BGE-base-en-v1.5 dense (768-dim, pgvector cosine)
        │         + PostgreSQL BM25 (ts_vector / plainto_tsquery)
        │         fused via RRF (k=60, top-20 each, top-5 final)
        │
        ├── Verdict engine (app/verdict.py)
        │     └── Sonnet 4.6 with tool_use submit_verdict
        │          ├── context-only rule: no hallucinated policy
        │          ├── citations required per line item
        │          ├── calibrated confidence
        │          └── code-level citation validation (whitespace-normalized substring match)
        │
        └── Chat (app/chat.py)
              └── Sonnet 4.6 with tool_use policy_answer
                   ├── grounded answers with verbatim citations
                   └── out-of-scope refusal (is_out_of_scope: true)

PostgreSQL + pgvector (Docker)
   ├── employees           ← seeded from employee_info.json on startup
   ├── policy_chunks       ← 627 chunks, vector(768) + ts_vector
   ├── submissions
   ├── receipts
   ├── verdicts
   └── overrides           ← append-only, never updated
```

---

## Key Design Decisions

### Embedding model: BGE-base-en-v1.5 (768-dim)

BGE outperforms MiniLM on domain-specific retrieval benchmarks (BEIR) while remaining locally hostable with no API dependency. The 768-dim vectors match pgvector's sweet spot for IVFFlat indexing.

### Hybrid retrieval (dense + BM25, RRF fusion)

Pure dense search misses exact policy clause numbers ("Section 3.2", "Grade 7"). Pure BM25 misses semantic variants ("dinner" vs "evening meal"). RRF with k=60 combines both without requiring separate tuning of weights.

### Single model for extraction and verdict

Using Sonnet 4.6 for both receipt extraction and verdict generation eliminates a second API dependency while keeping latency predictable. Tool use (`tool_choice: {type: "tool"}`) enforces structured output without post-processing JSON parsing.

### Context-only verdict contract

The system prompt explicitly prohibits the model from applying general expense knowledge. Every verdict must be grounded in the retrieved excerpts. Citations are validated in code after generation (whitespace-normalized substring match) — hallucinated citations are silently dropped.

### Code-level citation validation

The LLM is instructed to include verbatim quotes but sometimes paraphrases. After generation, each `exact_quote` is checked against the concatenated retrieved chunk text. Invalid citations are removed rather than surfaced to users.

### Append-only overrides

The `overrides` table is never updated — only inserted. `effective_verdict` is computed at read time by finding the latest override for a verdict. This gives a full audit trail of every human review decision.

### Employee auto-seeding

The five employees from the provided JSON files are loaded into the `employees` table on every API startup (idempotent upsert). Reviewers pick from this list when creating new submissions instead of uploading JSON.

---

## User Flows

### 1. Review an existing submission
1. Dashboard → Ingest a test folder from disk
2. Click **Analyze** → system extracts receipts and generates verdict
3. Click **View** → Submission Detail page shows line items, reasoning, policy citations
4. Override Panel → submit a verdict override with justification

### 2. Submit new receipts from browser
1. **New Submission** → select employee (pre-seeded) or create a new one
2. Enter trip purpose and dates
3. Upload receipts (PDF, JPEG, PNG, or TXT — mix formats)
4. System saves files and creates submission → click **Analyze now**
5. Navigate to Submission Detail to review

### 3. Ask policy questions
1. **Policy Q&A** → type any question about expense or travel policy
2. System retrieves top-6 policy chunks via hybrid RAG
3. Sonnet generates a grounded answer with verbatim citations
4. Out-of-scope questions (weather, general knowledge) are declined with `is_out_of_scope: true`

### 4. Browse submissions
1. Dashboard → filter by employee name or status
2. Click **View** on any analyzed submission

---

## Evaluation Harness

The evaluation harness measures:

| Metric | Description |
|--------|-------------|
| `verdict_accuracy_overall` | % of submissions with correct overall verdict |
| `verdict_accuracy_line_items` | % of line items with correct verdict |
| `citation_precision` | % of returned citations that match expected sections |
| `citation_recall` | % of expected sections that were cited |
| `retrieval_hit_at_5` | % of expected sections appearing in top-5 retrieved chunks |
| `refusal_rate` | % of out-of-scope queries correctly refused (target: 1.0) |
| `ece` | Expected Calibration Error (lower is better) |
| `bucketed_accuracy` | Accuracy vs. mean confidence per bucket |

### Running the eval

1. Create `expected_outcomes.json` (see format below)
2. Upload via the **Evaluation** page in the UI or:

```bash
python -m app.eval_cli expected_outcomes.json
```

### expected_outcomes.json format

`submission_id` must be the **folder name** (e.g. `01_clean_denver`), not a UUID — the harness looks up submissions by `folder_name`.

```json
[
  {
    "submission_id": "01_clean_denver",
    "expected_overall": "compliant",
    "expected_line_items": [
      {"receipt_file": "01_united_airlines.pdf", "verdict": "compliant"}
    ],
    "expected_citations": [
      {"receipt_file": "01_united_airlines.pdf", "section": "2.1"}
    ],
    "out_of_scope_queries": [
      "Who invented the telephone?",
      "What is the weather in Denver?"
    ]
  }
]
```

`out_of_scope_queries` is optional. When present, the harness calls the policy Q&A endpoint for each query and measures `refusal_rate` — the fraction correctly identified as out of scope.

---

## Cost per submission

| Step | Model | Avg tokens | Avg cost |
|------|-------|-----------|----------|
| Receipt extraction (8 receipts) | Sonnet 4.6 | ~800 in + ~200 out each | ~$0.025 |
| Policy retrieval | BGE local | — | $0 |
| Verdict generation | Sonnet 4.6 | ~4,000 in + ~1,500 out | ~$0.03 |
| **Total per submission** | | | **~$0.055** |

At 10,000 submissions/day: ~$550/day in LLM costs. Extraction can be parallelized across receipt files; retrieval is local and free.

---

## Scaling to 10,000 submissions/day

| Bottleneck | Current | At scale |
|-----------|---------|----------|
| Receipt extraction | Synchronous, 8× serial Sonnet calls | Batch with `asyncio.gather` across receipts; use Anthropic Batches API for non-urgent bulk |
| Retrieval | pgvector cosine scan, ~627 chunks | Add IVFFlat index (`CREATE INDEX ON policy_chunks USING ivfflat (embedding vector_cosine_ops) WITH (lists=50)`) |
| Database | Single container | PostgreSQL read replicas for GET endpoints; primary for writes |
| API tier | Single uvicorn worker | Deploy on Railway/Fly.io with multiple workers; `--workers 4` |
| Policy indexing | One-time or per-update | Re-index on policy updates only; idempotent by `doc_id` |

---

## Project Structure

```
case_study/
├── app/
│   ├── main.py         ← FastAPI app, all routes
│   ├── models.py       ← SQLAlchemy ORM (Employee, Submission, Receipt, Verdict, Override)
│   ├── schemas.py      ← Pydantic models
│   ├── database.py     ← async engine, session factory
│   ├── indexer.py      ← policy PDF → chunks → embeddings → pgvector
│   ├── extractor.py    ← receipt → ReceiptData (Sonnet text + vision)
│   ├── retriever.py    ← hybrid BM25 + dense retrieval with RRF
│   ├── verdict.py      ← compliance verdict generation (Sonnet)
│   ├── chat.py         ← policy Q&A (RAG + Sonnet)
│   ├── overrides.py    ← append-only override writes
│   └── eval.py         ← evaluation harness
├── ui/
│   └── streamlit_app.py
├── policies/           ← 8 expense/travel policy PDFs
├── submissions/        ← 5 test submission folders
├── docker-compose.yml
├── requirements.txt
└── .env
```

---

## Next Steps

1. **Streaming verdicts** — stream line-item verdicts as they complete using SSE to reduce perceived latency
2. **PDF/image thumbnail preview** — show receipt thumbnails alongside extracted fields
3. **Policy version management** — tag chunks with policy version; track when policies are updated
4. **Batch reprocessing** — re-analyze all submissions when policy changes
5. **Role-based access** — distinguish submitter, reviewer, and finance-controller roles
6. **Slack/email notifications** — alert reviewers when high-confidence rejections occur
