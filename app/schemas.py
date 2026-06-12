from __future__ import annotations
from typing import Literal, Optional
from pydantic import BaseModel, Field
import uuid
from datetime import datetime


class ReceiptData(BaseModel):
    vendor: str
    date: str
    amount: float
    currency: str = "USD"
    category: Literal["meal", "hotel", "transport", "other"]
    attendees: list[str] = Field(default_factory=list)
    business_purpose: str
    raw_text: str
    input_type: Literal["text", "image"] = "text"


class Citation(BaseModel):
    doc_id: str
    section: str
    page: int
    exact_quote: str


class LineItemVerdict(BaseModel):
    receipt_file: str
    amount: float
    category: str
    verdict: Literal["compliant", "flagged", "rejected"]
    policy_citations: list[Citation] = Field(default_factory=list)
    reasoning: str
    confidence: float = Field(ge=0.0, le=1.0)


class SubmissionVerdict(BaseModel):
    submission_id: str
    overall: Literal["compliant", "flagged", "rejected"]
    total_amount: float
    approved_amount: float
    line_items: list[LineItemVerdict]
    summary: str
    confidence: float = Field(ge=0.0, le=1.0)


class OverrideCreate(BaseModel):
    verdict_id: uuid.UUID
    reviewer_id: str
    new_verdict: Literal["compliant", "flagged", "rejected"]
    justification: str = Field(min_length=10)


class OverrideRead(BaseModel):
    id: uuid.UUID
    verdict_id: uuid.UUID
    reviewer_id: str
    original_verdict: str
    new_verdict: str
    justification: str
    created_at: datetime

    model_config = {"from_attributes": True}


class SubmissionRead(BaseModel):
    id: uuid.UUID
    folder_name: str
    employee_json: dict
    status: str
    created_at: datetime
    effective_verdict: Optional[str] = None
    confidence: Optional[float] = None

    model_config = {"from_attributes": True}


class EmployeeCreate(BaseModel):
    employee_id: str
    name: str
    grade: int
    title: str
    department: str
    manager_id: Optional[str] = None
    home_base: Optional[str] = None


class EmployeeRead(EmployeeCreate):
    id: uuid.UUID
    created_at: datetime
    model_config = {"from_attributes": True}


class ChatCitation(BaseModel):
    doc_id: str
    section: str
    page: int
    exact_quote: str


class ChatResponse(BaseModel):
    answer: str
    is_out_of_scope: bool = False
    citations: list[ChatCitation] = Field(default_factory=list)
    retrieved_chunks: list[dict] = Field(default_factory=list)


class EvalExpectedLineItem(BaseModel):
    receipt_file: str
    verdict: str


class EvalExpectedCitation(BaseModel):
    receipt_file: str
    section: str


class EvalExpectedOutcome(BaseModel):
    submission_id: str
    expected_overall: str
    expected_line_items: list[EvalExpectedLineItem] = Field(default_factory=list)
    expected_citations: list[EvalExpectedCitation] = Field(default_factory=list)
    out_of_scope_queries: list[str] = Field(default_factory=list)  # should all be refused


class BucketedAccuracy(BaseModel):
    bucket: str
    count: int
    mean_confidence: float
    accuracy: float
    calibration_error: float


class EvalResult(BaseModel):
    run_at: str
    verdict_accuracy_overall: float
    verdict_accuracy_line_items: float
    citation_precision: float
    citation_recall: float
    retrieval_hit_at_5: float
    refusal_rate: float
    ece: float
    bucketed_accuracy: list[BucketedAccuracy]
    per_submission: list[dict]
