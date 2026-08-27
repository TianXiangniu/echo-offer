from __future__ import annotations

import re
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Literal, Protocol

import pymupdf
from docx import Document
from docx.document import Document as DocumentObject
from docx.oxml.table import CT_Tbl
from docx.oxml.text.paragraph import CT_P
from docx.table import Table
from docx.text.paragraph import Paragraph


ResumeSourceType = Literal["pdf", "docx"]
MIN_EXTRACTED_CHARACTERS = 40


class ResumeParserError(Exception):
    code = "invalid_document"


class InvalidDocumentError(ResumeParserError):
    code = "invalid_document"


class NoExtractableTextError(ResumeParserError):
    code = "no_extractable_text"


class UnsupportedDocumentTypeError(ResumeParserError):
    code = "unsupported_file_type"


@dataclass(frozen=True)
class ParsedResume:
    source_type: ResumeSourceType
    text: str
    unit_count: int
    warnings: list[str]


class ResumeParser(Protocol):
    source_type: ResumeSourceType

    def parse(
        self,
        file_bytes: bytes,
        filename: str,
        content_type: str | None,
    ) -> ParsedResume:
        ...


def normalize_text(text: str) -> str:
    normalized_lines = [line.rstrip() for line in text.replace("\r\n", "\n").replace("\r", "\n").replace("\x00", "").split("\n")]
    normalized = "\n".join(normalized_lines)
    normalized = re.sub(r"\n{3,}", "\n\n", normalized)
    return normalized.strip()


def _ensure_enough_text(text: str) -> str:
    normalized = normalize_text(text)
    if len("".join(normalized.split())) < MIN_EXTRACTED_CHARACTERS:
        raise NoExtractableTextError(
            "文档中没有足够的可提取文本，扫描件 OCR 暂不支持，请粘贴文本或手动录入。"
        )
    return normalized


class PdfResumeParser:
    source_type: ResumeSourceType = "pdf"

    def parse(
        self,
        file_bytes: bytes,
        filename: str,
        content_type: str | None,
    ) -> ParsedResume:
        del filename, content_type
        try:
            document = pymupdf.open(stream=file_bytes, filetype="pdf")
        except Exception as exc:
            raise InvalidDocumentError("PDF 文件损坏或无法解析。") from exc

        page_texts: list[str] = []
        try:
            for index, page in enumerate(document):
                page_text = page.get_text("text", sort=True).strip()
                if page_text:
                    page_texts.append(f"--- 第 {index + 1} 页 ---\n{page_text}")
            text = _ensure_enough_text("\n\n".join(page_texts))
            return ParsedResume(
                source_type=self.source_type,
                text=text,
                unit_count=document.page_count,
                warnings=[],
            )
        except NoExtractableTextError:
            raise
        except Exception as exc:
            raise InvalidDocumentError("PDF 文件损坏或无法解析。") from exc
        finally:
            document.close()


def _iter_docx_blocks(document: DocumentObject):
    for child in document.element.body.iterchildren():
        if isinstance(child, CT_P):
            yield Paragraph(child, document)
        elif isinstance(child, CT_Tbl):
            yield Table(child, document)


class DocxResumeParser:
    source_type: ResumeSourceType = "docx"

    def parse(
        self,
        file_bytes: bytes,
        filename: str,
        content_type: str | None,
    ) -> ParsedResume:
        del filename, content_type
        try:
            document = Document(BytesIO(file_bytes))
            blocks: list[str] = []
            for block in _iter_docx_blocks(document):
                if isinstance(block, Paragraph):
                    value = block.text.strip()
                    if value:
                        blocks.append(value)
                elif isinstance(block, Table):
                    for row in block.rows:
                        value = "\t".join(cell.text.strip() for cell in row.cells).strip()
                        if value:
                            blocks.append(value)
            text = _ensure_enough_text("\n".join(blocks))
            return ParsedResume(
                source_type=self.source_type,
                text=text,
                unit_count=len(blocks),
                warnings=[],
            )
        except NoExtractableTextError:
            raise
        except Exception as exc:
            raise InvalidDocumentError("DOCX 文件损坏或无法解析。") from exc


class ResumeParserRegistry:
    _parsers: dict[str, type[ResumeParser]] = {
        ".pdf": PdfResumeParser,
        ".docx": DocxResumeParser,
    }

    @classmethod
    def for_file(cls, filename: str, content_type: str | None) -> ResumeParser:
        del content_type
        suffix = Path(filename or "").suffix.lower()
        parser_type = cls._parsers.get(suffix)
        if parser_type is None:
            raise UnsupportedDocumentTypeError("仅支持 PDF 和 DOCX 文件。")
        return parser_type()
