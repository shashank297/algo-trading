"""Optional OCR adapter that preserves the original PDF and derivative hash."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from tools.nifty200_pit.models import SourceRecord
from tools.nifty200_pit.source_catalogue import sha256_file


class OCRUnavailable(RuntimeError):
    pass


def load_pdf_transcription(source: SourceRecord) -> dict[str, Any] | None:
    """Load a bundled visual extraction only for the matching first-party PDF.

    This is an extraction derivative, not human approval or an identity map.
    Unknown scans remain unresolved; filenames alone never select evidence.
    """
    digest = source.source_sha256
    if source.source_tier not in {"A1", "A2"} or len(digest) != 64 or any(
        char not in "0123456789abcdef" for char in digest
    ):
        return None
    derivative = Path(__file__).with_name("transcriptions") / f"{digest}.json"
    parent = Path(source.local_path)
    if not derivative.is_file() or not parent.is_file() or sha256_file(parent) != digest:
        return None
    content = derivative.read_bytes()
    payload = json.loads(content)
    if payload["parent_sha256"] != digest:
        raise ValueError("PDF transcription parent hash mismatch")
    return dict(payload, derivative_sha256=hashlib.sha256(content).hexdigest())


def ocr_pdf(input_path: str | Path, output_path: str | Path) -> dict[str, str]:
    """OCR a PDF through optional dependencies and bind derivative to parent hash."""
    try:
        import pytesseract
        from pdf2image import convert_from_path
    except ImportError as exc:
        raise OCRUnavailable("OCR requires pytesseract and pdf2image") from exc
    input_file, output_file = Path(input_path), Path(output_path)
    pages = convert_from_path(str(input_file))
    text = "\n\n".join(pytesseract.image_to_string(page) for page in pages)
    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_text(text, encoding="utf-8")
    return {"parent_sha256": sha256_file(input_file), "ocr_sha256": sha256_file(output_file), "output_path": str(output_file)}
