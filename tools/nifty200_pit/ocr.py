"""Optional OCR adapter that preserves the original PDF and derivative hash."""

from __future__ import annotations

from pathlib import Path

from tools.nifty200_pit.source_catalogue import sha256_file


class OCRUnavailable(RuntimeError):
    pass


def extract_ocr_pages(input_path: str | Path) -> list[str]:
    """Recover page text locally; callers must retain OCR rows for manual review."""
    try:
        import pypdfium2
        from rapidocr_onnxruntime import RapidOCR
    except ImportError as exc:
        raise OCRUnavailable('Scanned releases require pypdfium2 and rapidocr_onnxruntime') from exc
    engine = RapidOCR()
    pages: list[str] = []
    with pypdfium2.PdfDocument(str(input_path)) as document:
        for index in range(len(document)):
            page = document[index]
            try:
                bitmap = page.render(scale=2)
                try:
                    rows, _ = engine(bitmap.to_numpy())
                finally:
                    bitmap.close()
            finally:
                page.close()
            # Rejoin cells on the same visual line; keep neighboring index
            # headings so the ordinary section-boundary parser can exclude them.
            lines: list[list[tuple[float, str]]] = []
            baseline: float | None = None
            for box, text, _score in sorted(rows or [], key=lambda row: (
                sum(p[1] for p in row[0]) / 4, min(p[0] for p in row[0]), row[1],
                tuple(coordinate for point in row[0] for coordinate in point),
            )):
                y = sum(point[1] for point in box) / 4
                height = max(point[1] for point in box) - min(point[1] for point in box)
                if baseline is None or abs(y - baseline) > height / 2:
                    lines.append([])
                    baseline = y
                lines[-1].append((min(point[0] for point in box), text))
            pages.append('\n'.join(' '.join(text for _, text in sorted(line)) for line in lines))
    return pages


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
