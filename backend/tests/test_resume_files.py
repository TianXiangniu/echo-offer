import asyncio
from io import BytesIO
from pathlib import Path

import pytest
import pymupdf
from docx import Document
from fastapi import UploadFile

from app.resume_files import (
    FileTooLargeError,
    InvalidResumeFileError,
    UnsupportedResumeTypeError,
    read_upload_bytes,
    store_resume_file,
    validate_resume_upload,
)


@pytest.fixture
def pdf_bytes():
    document = pymupdf.open()
    page = document.new_page()
    page.insert_textbox(
        pymupdf.Rect(72, 72, 520, 180),
        "Project experience: built a retrieval augmented generation agent.",
    )
    try:
        return document.tobytes()
    finally:
        document.close()


@pytest.fixture
def docx_bytes():
    document = Document()
    document.add_paragraph(
        "工作经历：负责企业知识库 Agent 后端开发，设计检索链路并维护稳定性。"
    )
    output = BytesIO()
    document.save(output)
    return output.getvalue()


def test_pdf_signature_is_required():
    with pytest.raises(InvalidResumeFileError) as caught:
        validate_resume_upload("resume.pdf", "application/pdf", b"not a pdf")

    assert caught.value.code == "invalid_file_signature"


def test_unsupported_extension_is_rejected(pdf_bytes):
    with pytest.raises(UnsupportedResumeTypeError) as caught:
        validate_resume_upload("resume.txt", "text/plain", pdf_bytes)

    assert caught.value.code == "unsupported_file_type"


def test_mismatched_mime_is_rejected(pdf_bytes):
    with pytest.raises(UnsupportedResumeTypeError):
        validate_resume_upload("resume.pdf", "application/msword", pdf_bytes)


def test_docx_container_is_validated(docx_bytes):
    validated = validate_resume_upload(
        "resume.docx",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        docx_bytes,
    )

    assert validated.source_type == "docx"


def test_upload_size_is_limited(pdf_bytes):
    with pytest.raises(FileTooLargeError) as caught:
        validate_resume_upload("resume.pdf", "application/pdf", pdf_bytes + b"x" * (10 * 1024 * 1024))

    assert caught.value.code == "file_too_large"


def test_storage_uses_a_random_filename(tmp_path, pdf_bytes):
    validated = validate_resume_upload("我的简历.pdf", "application/pdf", pdf_bytes)
    stored = store_resume_file(pdf_bytes, validated.source_type, tmp_path)

    assert stored.relative_path.parent == Path(".")
    assert stored.relative_path.suffix == ".pdf"
    assert stored.relative_path.name != "我的简历.pdf"
    assert (tmp_path / stored.relative_path).read_bytes() == pdf_bytes
    assert len(stored.file_hash) == 64


def test_read_upload_bytes_stops_at_limit():
    upload = UploadFile(file=BytesIO(b"12345"), filename="resume.pdf")

    with pytest.raises(FileTooLargeError):
        asyncio.run(read_upload_bytes(upload, 4))
