"""Optional OCR adapter that preserves the original PDF and derivative hash."""

from __future__ import annotations

from pathlib import Path

from tools.nifty200_pit.source_catalogue import sha256_file


class OCRUnavailable(RuntimeError):
    pass


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
