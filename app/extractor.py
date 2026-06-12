"""
Receipt extractor — two paths:
  text path: PDF with text layer or .txt → Sonnet text call
  image path: .jpg/.png or scanned PDF → Sonnet vision call
"""
import base64
import io
import os
from pathlib import Path

import anthropic
import fitz  # PyMuPDF

from app.schemas import ReceiptData

from dotenv import load_dotenv
load_dotenv(override=True)

_client: anthropic.Anthropic | None = None

EXTRACTION_TOOL = {
    "name": "extract_receipt",
    "description": "Extract structured fields from an expense receipt",
    "input_schema": {
        "type": "object",
        "properties": {
            "vendor": {"type": "string"},
            "date": {"type": "string", "description": "ISO 8601 date (YYYY-MM-DD)"},
            "amount": {"type": "number"},
            "currency": {"type": "string", "default": "USD"},
            "category": {
                "type": "string",
                "enum": ["meal", "hotel", "transport", "other"]
            },
            "attendees": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Names of attendees if mentioned"
            },
            "business_purpose": {"type": "string"},
        },
        "required": ["vendor", "date", "amount", "currency", "category", "business_purpose"],
    },
}

SYSTEM_PROMPT = (
    "You are an expense receipt parser. Extract structured fields exactly as they appear. "
    "For dates use ISO 8601 (YYYY-MM-DD). For amounts use the numeric value only. "
    "If a field is not present, use a sensible default. Never hallucinate values."
)


def client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    return _client


def is_scanned_pdf(pdf_path: Path) -> tuple[bool, str]:
    """Return (is_scanned, extracted_text). Scanned if chars/page < 100."""
    doc = fitz.open(str(pdf_path))
    texts = [doc[i].get_text("text") for i in range(len(doc))]
    doc.close()
    full_text = "\n".join(texts)
    avg_chars = len(full_text) / max(len(texts), 1)
    return avg_chars < 100, full_text


def pdf_to_image_base64(pdf_path: Path) -> str:
    doc = fitz.open(str(pdf_path))
    page = doc[0]
    mat = fitz.Matrix(2.0, 2.0)  # 2x zoom for readability
    pix = page.get_pixmap(matrix=mat)
    doc.close()
    img_bytes = pix.tobytes("png")
    return base64.standard_b64encode(img_bytes).decode()


def image_file_to_base64(image_path: Path) -> tuple[str, str]:
    suffix = image_path.suffix.lower()
    media_type = "image/jpeg" if suffix in (".jpg", ".jpeg") else "image/png"
    with open(image_path, "rb") as f:
        data = base64.standard_b64encode(f.read()).decode()
    return data, media_type


def call_sonnet_text(text: str) -> dict:
    response = client().messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1024,
        system=SYSTEM_PROMPT,
        tools=[EXTRACTION_TOOL],
        tool_choice={"type": "tool", "name": "extract_receipt"},
        messages=[{"role": "user", "content": f"Extract fields from this receipt:\n\n{text}"}],
    )
    for block in response.content:
        if block.type == "tool_use" and block.name == "extract_receipt":
            return block.input
    raise ValueError("Sonnet did not return tool use block")


def call_sonnet_vision(image_b64: str, media_type: str = "image/png") -> dict:
    response = client().messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1024,
        system=SYSTEM_PROMPT,
        tools=[EXTRACTION_TOOL],
        tool_choice={"type": "tool", "name": "extract_receipt"},
        messages=[{
            "role": "user",
            "content": [
                {
                    "type": "image",
                    "source": {"type": "base64", "media_type": media_type, "data": image_b64},
                },
                {"type": "text", "text": "Extract fields from this expense receipt image."},
            ],
        }],
    )
    for block in response.content:
        if block.type == "tool_use" and block.name == "extract_receipt":
            return block.input
    raise ValueError("Sonnet did not return tool use block")


def extract_receipt(receipt_path: Path) -> ReceiptData:
    suffix = receipt_path.suffix.lower()

    if suffix == ".txt":
        raw_text = receipt_path.read_text(encoding="utf-8", errors="replace")
        fields = call_sonnet_text(raw_text)
        return ReceiptData(**fields, raw_text=raw_text, input_type="text")

    if suffix == ".pdf":
        is_scanned, raw_text = is_scanned_pdf(receipt_path)
        if is_scanned:
            image_b64 = pdf_to_image_base64(receipt_path)
            fields = call_sonnet_vision(image_b64, "image/png")
            return ReceiptData(**fields, raw_text=raw_text or "[scanned]", input_type="image")
        else:
            fields = call_sonnet_text(raw_text)
            return ReceiptData(**fields, raw_text=raw_text, input_type="text")

    if suffix in (".jpg", ".jpeg", ".png"):
        image_b64, media_type = image_file_to_base64(receipt_path)
        fields = call_sonnet_vision(image_b64, media_type)
        return ReceiptData(**fields, raw_text="[image]", input_type="image")

    raise ValueError(f"Unsupported receipt format: {suffix}")
