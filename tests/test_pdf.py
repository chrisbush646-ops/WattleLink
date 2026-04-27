import io

import pytest

from apps.literature.services.pdf import MAX_PDF_SIZE_BYTES, validate_upload


class FakeFile:
    """Minimal file-like object for testing validate_upload."""

    def __init__(self, content: bytes, size: int | None = None):
        self._buf = io.BytesIO(content)
        self.size = size if size is not None else len(content)

    def read(self, n=-1):
        return self._buf.read(n)

    def seek(self, pos):
        self._buf.seek(pos)


VALID_PDF_HEADER = b"%PDF-1.4 sample content"


class TestValidateUpload:
    def test_valid_pdf_passes(self):
        f = FakeFile(VALID_PDF_HEADER)
        validate_upload(f)  # should not raise

    def test_non_pdf_magic_bytes_raises(self):
        f = FakeFile(b"PK\x03\x04 this is a zip file")
        with pytest.raises(ValueError, match="not a valid PDF"):
            validate_upload(f)

    def test_empty_file_raises(self):
        f = FakeFile(b"")
        with pytest.raises(ValueError, match="not a valid PDF"):
            validate_upload(f)

    def test_too_large_raises(self):
        f = FakeFile(VALID_PDF_HEADER, size=MAX_PDF_SIZE_BYTES + 1)
        with pytest.raises(ValueError, match="exceeds maximum size"):
            validate_upload(f)

    def test_exactly_max_size_passes(self):
        f = FakeFile(VALID_PDF_HEADER, size=MAX_PDF_SIZE_BYTES)
        validate_upload(f)  # should not raise

    def test_partial_pdf_header_raises(self):
        # Only 4 bytes of the 5-byte magic bytes prefix
        f = FakeFile(b"%PDF")
        with pytest.raises(ValueError, match="not a valid PDF"):
            validate_upload(f)

    def test_seek_resets_after_header_read(self):
        f = FakeFile(VALID_PDF_HEADER)
        validate_upload(f)
        # After validation, position should be at 0 so the caller can re-read
        assert f._buf.tell() == 0

    def test_html_disguised_as_pdf_raises(self):
        f = FakeFile(b"<html><body>not a pdf</body></html>")
        with pytest.raises(ValueError, match="not a valid PDF"):
            validate_upload(f)
