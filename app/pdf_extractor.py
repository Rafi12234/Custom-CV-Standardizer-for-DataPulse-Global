# app/pdf_extractor.py
# Extracts selectable (copyable) text from PDF files using PyMuPDF.

from pathlib import Path

import fitz  # PyMuPDF

from app.config import MIN_TEXT_LENGTH


def extract_text(pdf_path:  Path) -> str:
    """
    Extract all selectable text from a PDF file.

    Parameters
    ----------
    pdf_path : Path
        Path to the PDF file.

    Returns
    -------
    str
        The full extracted text from every page.

    Raises
    ------
    ValueError
        If the PDF contains no selectable text (e.g. scanned / image-only PDF).
    RuntimeError
        If the file cannot be opened or is corrupted.
    """
    try:
        doc = fitz.open(str(pdf_path))
    except Exception as exc:
        raise RuntimeError(
            f"Cannot open PDF '{pdf_path.name}': {exc}"
        ) from exc

    pages_text: list[str] = []

    try:
        for page_index in range(len(doc)):
            page = doc.load_page(page_index)
            page_text = page.get_text("text")          # extract selectable text
            if page_text:
                pages_text.append(page_text)
    finally:
        doc.close()

    full_text = "\n".join(pages_text).strip()

    if len(full_text) < MIN_TEXT_LENGTH:
        raise ValueError(
            f"PDF '{pdf_path.name}' contains no meaningful selectable text "
            f"(extracted {len(full_text)} characters, minimum is {MIN_TEXT_LENGTH}). "
            "This may be a scanned or image-based PDF which is not supported."
        )

    return full_text