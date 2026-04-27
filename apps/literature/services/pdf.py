import logging
from pathlib import Path

logger = logging.getLogger(__name__)

MAX_PDF_SIZE_MB = 50
MAX_PDF_SIZE_BYTES = MAX_PDF_SIZE_MB * 1024 * 1024


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
