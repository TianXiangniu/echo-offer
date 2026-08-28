from __future__ import annotations

import hashlib
import zipfile
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Literal
from uuid import uuid4

from fastapi import UploadFile

from .config import MAX_RESUME_UPLOAD_BYTES
from .resume_parsers import ResumeSourceType


PDF_MIME = "application/pdf"
DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


class ResumeUploadError(Exception):
    status_code = 422
    code = "invalid_upload"


class FileTooLargeError(ResumeUploadError):
    status_code = 413
    code = "file_too_large"


class UnsupportedResumeTypeError(ResumeUploadError):
    status_code = 415
    code = "unsupported_file_type"


class InvalidResumeFileError(ResumeUploadError):
    status_code = 422
    code = "invalid_file_signature"


@dataclass(frozen=True)
class ValidatedResumeFile:
    source_type: ResumeSourceType
    original_filename: str
    content_type: str | None


@dataclass(frozen=True)
class StoredResumeFile:
    relative_path: Path
    file_hash: str


def _source_type_for_filename(filename: str | None) -> ResumeSourceType:
    suffix = Path(filename or "").suffix.lower()
    if suffix == ".pdf":
        return "pdf"
    if suffix == ".docx":
        return "docx"
    raise UnsupportedResumeTypeError("仅支持 PDF 和 DOCX 文件。")


def _validate_mime(source_type: ResumeSourceType, content_type: str | None) -> str | None:
    if not content_type:
        return None
    normalized = content_type.split(";", 1)[0].strip().lower()
    expected = PDF_MIME if source_type == "pdf" else DOCX_MIME
    if normalized != expected:
        raise UnsupportedResumeTypeError("文件类型与扩展名不匹配。")
    return normalized


def _validate_docx_container(file_bytes: bytes) -> None:
    try:
        with zipfile.ZipFile(BytesIO(file_bytes)) as archive:
            names = set(archive.namelist())
            required = {"[Content_Types].xml", "word/document.xml"}
            if not required.issubset(names):
                raise InvalidResumeFileError("DOCX 文件结构不完整。")
    except InvalidResumeFileError:
        raise
    except (OSError, zipfile.BadZipFile, zipfile.LargeZipFile) as exc:
        raise InvalidResumeFileError("DOCX 文件结构无效。") from exc


def validate_resume_upload(
    filename: str | None,
    content_type: str | None,
    file_bytes: bytes,
) -> ValidatedResumeFile:
    if len(file_bytes) > MAX_RESUME_UPLOAD_BYTES:
        raise FileTooLargeError("文件超过 10 MiB 大小限制。")

    source_type = _source_type_for_filename(filename)
    normalized_content_type = _validate_mime(source_type, content_type)
    if source_type == "pdf":
        if not file_bytes.startswith(b"%PDF-"):
            raise InvalidResumeFileError("PDF 文件头无效。")
    else:
        _validate_docx_container(file_bytes)

    return ValidatedResumeFile(
        source_type=source_type,
        original_filename=filename or "resume" + (".pdf" if source_type == "pdf" else ".docx"),
        content_type=normalized_content_type,
    )


async def read_upload_bytes(upload: UploadFile, max_bytes: int = MAX_RESUME_UPLOAD_BYTES) -> bytes:
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await upload.read(64 * 1024)
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            raise FileTooLargeError("文件超过 10 MiB 大小限制。")
        chunks.append(chunk)
    return b"".join(chunks)


def store_resume_file(
    file_bytes: bytes,
    source_type: ResumeSourceType,
    upload_root: Path,
) -> StoredResumeFile:
    upload_root.mkdir(parents=True, exist_ok=True)
    suffix = ".pdf" if source_type == "pdf" else ".docx"
    relative_path = Path(f"{uuid4().hex}{suffix}")
    (upload_root / relative_path).write_bytes(file_bytes)
    file_hash = hashlib.sha256(file_bytes).hexdigest()
    return StoredResumeFile(relative_path=relative_path, file_hash=file_hash)
