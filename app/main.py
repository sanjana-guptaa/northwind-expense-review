from __future__ import annotations
import json
import os
import shutil
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import List
from dotenv import load_dotenv

load_dotenv(override=True)

from fastapi import FastAPI, HTTPException, Depends, UploadFile, File, Form
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import init_db, get_db, AsyncSessionLocal
from app.models import Employee, Submission, Receipt, Verdict, PolicyChunk, Override
from app.schemas import OverrideCreate, OverrideRead, SubmissionVerdict, EmployeeCreate
from app.extractor import extract_receipt
from app.verdict import generate_verdict
from app import overrides as override_svc
from app.eval import run_eval

SUBMISSIONS_DIR = Path(os.getenv("SUBMISSIONS_DIR", "./submissions"))
ALLOWED_EXTS = {".pdf", ".jpg", ".jpeg", ".png", ".txt"}


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()

    async with AsyncSessionLocal() as session:
        # Seed employees from submission JSON files
        for emp_file in sorted(SUBMISSIONS_DIR.glob("*/employee_info.json")):
            try:
                emp_data = json.loads(emp_file.read_text(encoding="utf-8"))
                emp_id = emp_data.get("employee_id")
                if emp_id:
                    existing = await session.scalar(
                        select(Employee).where(Employee.employee_id == emp_id)
                    )
                    if not existing:
                        session.add(Employee(
                            employee_id=emp_id,
                            name=emp_data.get("name", ""),
                            grade=int(emp_data.get("grade", 1)),
                            title=emp_data.get("title", ""),
                            department=emp_data.get("department", ""),
                            manager_id=emp_data.get("manager_id"),
                            home_base=emp_data.get("home_base"),
                        ))
            except Exception:
                pass
        await session.commit()

        # Warn if policies not indexed
        count = await session.scalar(select(PolicyChunk).limit(1))
        if count is None:
            import logging
            logging.getLogger("uvicorn").warning(
                "policy_chunks table is empty — run: python -m app.indexer"
            )
    yield


app = FastAPI(title="Northwind Expense Review", lifespan=lifespan)


# ─── Health ───────────────────────────────────────────────────────────────────

@app.get("/api/health")
async def health():
    return {"status": "ok"}


# ─── Employees ────────────────────────────────────────────────────────────────

@app.get("/api/employees")
async def list_employees(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Employee).order_by(Employee.name))
    employees = result.scalars().all()
    return [
        {
            "id": str(e.id),
            "employee_id": e.employee_id,
            "name": e.name,
            "grade": e.grade,
            "title": e.title,
            "department": e.department,
            "manager_id": e.manager_id,
            "home_base": e.home_base,
        }
        for e in employees
    ]


@app.post("/api/employees")
async def create_employee(data: EmployeeCreate, db: AsyncSession = Depends(get_db)):
    existing = await db.scalar(
        select(Employee).where(Employee.employee_id == data.employee_id)
    )
    if existing:
        raise HTTPException(409, f"Employee {data.employee_id} already exists")

    employee = Employee(
        employee_id=data.employee_id,
        name=data.name,
        grade=data.grade,
        title=data.title,
        department=data.department,
        manager_id=data.manager_id,
        home_base=data.home_base,
    )
    db.add(employee)
    await db.commit()
    await db.refresh(employee)
    return {"id": str(employee.id), "employee_id": employee.employee_id, "name": employee.name}


# ─── Submissions (disk-based) ─────────────────────────────────────────────────

@app.get("/api/submissions/available")
async def available_submissions(db: AsyncSession = Depends(get_db)):
    if not SUBMISSIONS_DIR.exists():
        return []
    all_folders = sorted([
        f.name for f in SUBMISSIONS_DIR.iterdir()
        if f.is_dir() and (f / "employee_info.json").exists()
    ])
    result = await db.execute(select(Submission.folder_name))
    ingested = {row[0] for row in result.all()}
    return [{"folder": f, "ingested": f in ingested} for f in all_folders]


@app.post("/api/submissions/ingest")
async def ingest_submission(folder_name: str, db: AsyncSession = Depends(get_db)):
    folder = SUBMISSIONS_DIR / folder_name
    if not folder.exists():
        raise HTTPException(404, f"Folder not found: {folder}")

    existing = await db.scalar(
        select(Submission).where(Submission.folder_name == folder_name)
    )
    if existing:
        return {"id": str(existing.id), "status": "already_ingested"}

    employee_file = folder / "employee_info.json"
    if not employee_file.exists():
        raise HTTPException(400, "employee_info.json not found in submission folder")

    employee = json.loads(employee_file.read_text(encoding="utf-8"))
    submission = Submission(folder_name=folder_name, employee_json=employee)
    db.add(submission)
    await db.flush()

    receipts_dir = folder / "receipts"
    if receipts_dir.exists():
        for receipt_file in sorted(receipts_dir.iterdir()):
            if receipt_file.suffix.lower() in ALLOWED_EXTS:
                db.add(Receipt(submission_id=submission.id, filename=receipt_file.name))

    submission.status = "ingested"
    await db.commit()
    return {"id": str(submission.id), "status": "ingested"}


# ─── Submissions (browser upload) ─────────────────────────────────────────────

@app.post("/api/submissions/upload")
async def upload_submission(
    employee_json: str = Form(...),
    files: List[UploadFile] = File(...),
    db: AsyncSession = Depends(get_db),
):
    """Create a new submission from browser-uploaded receipts."""
    import traceback
    try:
        emp = json.loads(employee_json)
    except json.JSONDecodeError:
        raise HTTPException(400, "Invalid employee_json — must be valid JSON")

    emp_id_slug = emp.get("employee_id", "new").replace("-", "").lower()
    folder_name = f"upload_{emp_id_slug}_{uuid.uuid4().hex[:6]}"
    folder = SUBMISSIONS_DIR / folder_name
    receipts_dir = folder / "receipts"
    receipts_dir.mkdir(parents=True, exist_ok=True)

    try:
        (folder / "employee_info.json").write_text(json.dumps(emp, indent=2))

        saved = []
        for f in files:
            if not f.filename:
                continue
            ext = Path(f.filename).suffix.lower()
            if ext in ALLOWED_EXTS:
                dest = receipts_dir / f.filename
                dest.write_bytes(await f.read())
                saved.append(f.filename)

        if not saved:
            shutil.rmtree(folder, ignore_errors=True)
            raise HTTPException(400, "No valid receipt files (.pdf .jpg .png .txt)")

        submission = Submission(folder_name=folder_name, employee_json=emp)
        db.add(submission)
        await db.flush()

        for filename in saved:
            db.add(Receipt(submission_id=submission.id, filename=filename))

        submission.status = "ingested"
        await db.commit()

        return {"id": str(submission.id), "folder_name": folder_name, "file_count": len(saved)}

    except HTTPException:
        raise
    except Exception as e:
        shutil.rmtree(folder, ignore_errors=True)
        raise HTTPException(500, f"{type(e).__name__}: {e}\n{traceback.format_exc()}")


# ─── Submissions (list + detail) ──────────────────────────────────────────────

@app.get("/api/submissions")
async def list_submissions(
    status: str | None = None,
    employee_name: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    stmt = select(Submission).order_by(Submission.created_at.desc())
    result = await db.execute(stmt)
    submissions = result.scalars().all()

    out = []
    for sub in submissions:
        emp_name = sub.employee_json.get("name", "")

        # Optional filters
        if status and sub.status != status:
            continue
        if employee_name and employee_name.lower() not in emp_name.lower():
            continue

        verdict_row = await db.scalar(
            select(Verdict)
            .where(Verdict.submission_id == sub.id)
            .order_by(Verdict.created_at.desc())
            .limit(1)
        )
        effective = None
        confidence = None
        if verdict_row:
            effective = verdict_row.overall
            confidence = verdict_row.confidence
            latest_override = await db.scalar(
                select(Override)
                .where(Override.verdict_id == verdict_row.id)
                .order_by(Override.created_at.desc())
                .limit(1)
            )
            if latest_override:
                effective = latest_override.new_verdict

        out.append({
            "id": str(sub.id),
            "folder_name": sub.folder_name,
            "employee_name": emp_name,
            "status": sub.status,
            "effective_verdict": effective,
            "confidence": confidence,
            "created_at": sub.created_at.isoformat(),
        })
    return out


@app.get("/api/submissions/{submission_id}")
async def get_submission(submission_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    sub = await db.get(Submission, submission_id)
    if not sub:
        raise HTTPException(404, "Submission not found")

    receipts_result = await db.execute(
        select(Receipt).where(Receipt.submission_id == submission_id)
    )
    receipts = receipts_result.scalars().all()

    verdict_row = await db.scalar(
        select(Verdict)
        .where(Verdict.submission_id == submission_id)
        .order_by(Verdict.created_at.desc())
        .limit(1)
    )

    overrides = []
    effective = None
    if verdict_row:
        effective = await override_svc.effective_verdict(verdict_row, db)
        overrides = await override_svc.get_overrides(submission_id, db)

    return {
        "id": str(sub.id),
        "folder_name": sub.folder_name,
        "employee": sub.employee_json,
        "status": sub.status,
        "receipts": [
            {
                "id": str(r.id),
                "filename": r.filename,
                "extracted": r.extracted_json,
                "input_type": r.input_type,
            }
            for r in receipts
        ],
        "verdict": verdict_row.verdict_json if verdict_row else None,
        "verdict_id": str(verdict_row.id) if verdict_row else None,
        "effective_verdict": effective,
        "overrides": [
            {
                "id": str(o.id),
                "reviewer_id": o.reviewer_id,
                "original_verdict": o.original_verdict,
                "new_verdict": o.new_verdict,
                "justification": o.justification,
                "created_at": o.created_at.isoformat(),
            }
            for o in overrides
        ],
    }


# ─── Analysis ─────────────────────────────────────────────────────────────────

@app.post("/api/submissions/{submission_id}/analyze")
async def analyze_submission(submission_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    import traceback
    try:
        sub = await db.get(Submission, submission_id)
        if not sub:
            raise HTTPException(404, "Submission not found")

        folder = SUBMISSIONS_DIR / sub.folder_name
        receipts_dir = folder / "receipts"

        receipts_result = await db.execute(
            select(Receipt).where(Receipt.submission_id == submission_id)
        )
        receipt_rows = receipts_result.scalars().all()

        extracted_receipts: list[tuple[str, any]] = []
        for receipt_row in receipt_rows:
            receipt_path = receipts_dir / receipt_row.filename
            if not receipt_path.exists():
                continue
            receipt_data = extract_receipt(receipt_path)
            receipt_row.raw_text = receipt_data.raw_text
            receipt_row.extracted_json = receipt_data.model_dump()
            receipt_row.input_type = receipt_data.input_type
            extracted_receipts.append((receipt_row.filename, receipt_data))

        await db.flush()

        verdict = await generate_verdict(
            str(submission_id),
            sub.employee_json,
            extracted_receipts,
            db,
        )

        verdict_row = Verdict(
            submission_id=submission_id,
            verdict_json=verdict.model_dump(),
            overall=verdict.overall,
            confidence=verdict.confidence,
        )
        db.add(verdict_row)
        sub.status = "analyzed"
        await db.commit()

        return verdict.model_dump()

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"{type(e).__name__}: {str(e)}\n{traceback.format_exc()}",
        )


# ─── Overrides ────────────────────────────────────────────────────────────────

@app.post("/api/overrides")
async def create_override(data: OverrideCreate, db: AsyncSession = Depends(get_db)):
    try:
        override = await override_svc.create_override(data, db)
        return {"id": str(override.id), "status": "created"}
    except ValueError as e:
        raise HTTPException(404, str(e))


@app.get("/api/overrides/{submission_id}")
async def get_overrides(submission_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    rows = await override_svc.get_overrides(submission_id, db)
    return [
        {
            "id": str(o.id),
            "reviewer_id": o.reviewer_id,
            "original_verdict": o.original_verdict,
            "new_verdict": o.new_verdict,
            "justification": o.justification,
            "created_at": o.created_at.isoformat(),
        }
        for o in rows
    ]


# ─── Policy search ────────────────────────────────────────────────────────────

@app.get("/api/policies/search")
async def search_policies(q: str, db: AsyncSession = Depends(get_db)):
    from app.retriever import retrieve
    chunks = await retrieve(q, db, top_k=10)
    return [
        {
            "doc_id": c.doc_id,
            "section": c.section,
            "page": c.page,
            "text": c.text[:500],
            "score": c.rrf_score,
        }
        for c in chunks
    ]


# ─── Policy Q&A (chat) ────────────────────────────────────────────────────────

@app.get("/api/chat")
async def chat(question: str, db: AsyncSession = Depends(get_db)):
    from app.chat import answer_question
    if not question or not question.strip():
        raise HTTPException(400, "question must not be empty")
    return await answer_question(question.strip(), db)


# ─── Evaluation ───────────────────────────────────────────────────────────────

@app.post("/api/eval")
async def run_evaluation(file: UploadFile = File(...), db: AsyncSession = Depends(get_db)):
    content = await file.read()
    expected = json.loads(content)
    result = await run_eval(expected, db)
    return result


@app.get("/api/eval/results")
async def list_eval_results():
    results_dir = Path("./eval_results")
    if not results_dir.exists():
        return []
    files = sorted(results_dir.glob("*.json"), reverse=True)
    out = []
    for f in files[:20]:
        data = json.loads(f.read_text())
        out.append({"filename": f.name, "run_at": data.get("run_at"), "ece": data.get("ece")})
    return out
