import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)

MAX_PDF_SIZE_MB = 50
MAX_PDF_SIZE_BYTES = MAX_PDF_SIZE_MB * 1024 * 1024

_DOI_RE = re.compile(r"\b(10\.\d{4,9}/[-._;()/:A-Z0-9a-z]+)", re.IGNORECASE)


def validate_upload(file) -> None:
    """Raise ValueError if the upload is not a valid PDF under 50 MB."""
    if file.size > MAX_PDF_SIZE_BYTES:
        raise ValueError(f"File exceeds maximum size of {MAX_PDF_SIZE_MB} MB.")

    # Check PDF magic bytes
    header = file.read(5)
    file.seek(0)
    if header != b"%PDF-":
        raise ValueError("Uploaded file is not a valid PDF.")


def extract_text(file_path: str) -> str:
    """Extract plain text from a PDF file using PyMuPDF."""
    import fitz  # PyMuPDF

    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"PDF file not found: {file_path}")

    text_parts = []
    with fitz.open(str(path)) as doc:
        for page in doc:
            text_parts.append(page.get_text("text"))

    return "\n".join(text_parts)


def extract_doi_from_pdf(file_path: str) -> str | None:
    """
    Extract a DOI from PDF metadata or first-page text.
    Returns the raw DOI string (unverified) or None if not found.
    """
    import fitz  # PyMuPDF

    path = Path(file_path)
    if not path.exists():
        return None

    try:
        with fitz.open(str(path)) as doc:
            # 1. Check PDF document metadata
            metadata_doi = (doc.metadata or {}).get("doi", "")
            if metadata_doi and metadata_doi.strip():
                return metadata_doi.strip()

            # 2. Regex search of first page text
            if len(doc) > 0:
                first_page_text = doc[0].get_text("text")
                match = _DOI_RE.search(first_page_text)
                if match:
                    return match.group(1)
    except Exception as exc:
        logger.warning("DOI extraction from PDF failed: %s", exc)

    return None
