# Resume PDF / DOCX Parsing Implementation Plan

> For agentic workers: REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Add a runnable resume-upload vertical slice that parses text-based PDF and DOCX files into editable text, preserves source metadata, and reuses the existing profile/project confirmation flow.

**Architecture:** A format registry selects a PDF or DOCX adapter behind one ResumeParser protocol. The upload route validates and stores the original file, persists a parsed Resume plus ResumeSource, and returns the extracted draft. The existing profile route accepts the returned resume_id and the user-edited final text. The frontend keeps project facts manually confirmed and starts the existing interview only after profile creation succeeds.

**Tech Stack:** FastAPI UploadFile and multipart forms, PyMuPDF, python-docx, SQLAlchemy 2 + SQLite, Pydantic 2, Next.js/TypeScript, pytest, and the existing Tailwind UI.

## Global Constraints

- Supported upload formats are .pdf and .docx only.
- PDF extraction is text-only; scanned PDF, image resume, and image-only DOCX return no_extractable_text; OCR is not implemented.
- Maximum upload size is 10 MiB.
- PDF extraction uses page.get_text("text", sort=True) and inserts page separators.
- DOCX extraction includes body paragraphs and tables in document order.
- Uploaded files use random names under data/uploads/; original filenames are display metadata only.
- The parser produces an editable draft; only user-confirmed resume_text and project fields enter the interview context.
- Existing pasted-text profile, interview, refresh recovery, idempotency, and report behavior must remain passing.
- Do not add DeepSeek, LangGraph, OCR, authentication, cloud storage, background jobs, or .doc support.

---

## Task 1: Add parser contracts and PDF/DOCX adapters

**Files:**
- Create: backend/app/resume_parsers.py
- Modify: backend/requirements.txt
- Create: backend/tests/test_resume_parsers.py

**Interfaces:**
- Produces ParsedResume, ResumeParser, PdfResumeParser, DocxResumeParser, and ResumeParserRegistry.
- ParsedResume fields: source_type: Literal["pdf", "docx"], text: str, unit_count: int, warnings: list[str].
- ResumeParser.parse(file_bytes: bytes, filename: str, content_type: str | None) -> ParsedResume.
- ResumeParserRegistry.for_file(filename: str, content_type: str | None) -> ResumeParser.

- [ ] Step 1: Add parser dependencies

Add these requirements while retaining the existing dependencies:

    PyMuPDF>=1.24,<2
    python-docx>=1.1,<2
    python-multipart>=0.0.9,<1

- [ ] Step 2: Write failing parser tests

Create backend/tests/test_resume_parsers.py. Generate a two-page PDF with PyMuPDF and a DOCX containing a paragraph plus a table. Assert:

    def test_pdf_parser_extracts_text_and_page_count(pdf_bytes):
        parsed = PdfResumeParser().parse(
            pdf_bytes, "resume.pdf", "application/pdf"
        )
        assert parsed.source_type == "pdf"
        assert parsed.unit_count == 2
        assert "项目经历" in parsed.text

    def test_docx_parser_extracts_paragraphs_and_tables(docx_bytes):
        parsed = DocxResumeParser().parse(
            docx_bytes,
            "resume.docx",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )
        assert parsed.source_type == "docx"
        assert "工作经历" in parsed.text
        assert "Python" in parsed.text

Also cover corrupted PDF, corrupted DOCX, and documents with fewer than 40 non-whitespace characters.

- [ ] Step 3: Run parser tests and verify failure

    python -m pytest backend/tests/test_resume_parsers.py -q

Expected: import or assertion failures because the parser module does not exist.

- [ ] Step 4: Implement the common parser contract

Define typed exceptions, a frozen ParsedResume dataclass, and the parser protocol. Add shared normalization that converts CRLF to LF, removes NUL characters, trims trailing whitespace per line, collapses three or more newlines to two, and removes leading/trailing blank lines.

- [ ] Step 5: Implement PDF parsing

Open bytes with pymupdf.open(stream=file_bytes, filetype="pdf"). Iterate pages, call page.get_text("text", sort=True), join pages with a page marker, normalize the result, and raise NoExtractableTextError if normalized text has fewer than 40 non-whitespace characters.

- [ ] Step 6: Implement DOCX parsing and registry

Use python-docx to read body paragraphs and tables in XML body order. Emit non-empty paragraphs and table rows with tab-separated cells, normalize the result, apply the same threshold, and register .pdf and .docx adapters.

- [ ] Step 7: Run parser tests and commit

    python -m pytest backend/tests/test_resume_parsers.py -q
    git add backend/app/resume_parsers.py backend/requirements.txt backend/tests/test_resume_parsers.py
    git commit -m "feat: add pdf and docx resume parsers"

Expected: all parser tests pass before the commit.

## Task 2: Add upload validation and safe storage

**Files:**
- Create: backend/app/resume_files.py
- Modify: backend/app/config.py
- Modify: .gitignore
- Create: backend/tests/test_resume_files.py

**Interfaces:**
- Produces ValidatedResumeFile, StoredResumeFile, validate_resume_upload(), read_upload_bytes(), and store_resume_file().
- validate_resume_upload(filename: str | None, content_type: str | None, file_bytes: bytes) -> ValidatedResumeFile.
- store_resume_file(file_bytes: bytes, source_type: Literal["pdf", "docx"], upload_root: Path) -> StoredResumeFile.

- [ ] Step 1: Write failing validation tests

Test valid PDF/DOCX, wrong extension, a mismatched non-empty MIME, PDF without %PDF-, DOCX without [Content_Types].xml or word/document.xml, and a payload larger than 10 MiB.

    def test_pdf_signature_is_required():
        with pytest.raises(InvalidResumeFileError) as caught:
            validate_resume_upload("resume.pdf", "application/pdf", b"not a pdf")
        assert caught.value.code == "invalid_file_signature"

    def test_storage_uses_a_random_filename(tmp_path, pdf_bytes):
        validated = validate_resume_upload("我的简历.pdf", "application/pdf", pdf_bytes)
        stored = store_resume_file(pdf_bytes, validated.source_type, tmp_path)
        assert stored.relative_path.suffix == ".pdf"
        assert stored.relative_path.name != "我的简历.pdf"
        assert (tmp_path / stored.relative_path).read_bytes() == pdf_bytes

- [ ] Step 2: Run validation tests and verify failure

    python -m pytest backend/tests/test_resume_files.py -q

Expected: import failures because resume_files.py does not exist.

- [ ] Step 3: Add configuration and typed upload errors

In backend/app/config.py add:

    MAX_RESUME_UPLOAD_BYTES = 10 * 1024 * 1024
    DEFAULT_UPLOAD_ROOT = BASE_DIR / "data" / "uploads"

Define errors carrying status_code and code: ResumeUploadError, FileTooLargeError (413, file_too_large), UnsupportedResumeTypeError (415, unsupported_file_type), and InvalidResumeFileError (422, invalid_file_signature).

- [ ] Step 4: Implement bounded reads and validation

Implement read_upload_bytes(upload: UploadFile, max_bytes: int) -> bytes as an async 64 KiB chunk loop. Raise FileTooLargeError as soon as accumulated bytes exceed the limit. Validate suffix, optional MIME, PDF signature, and DOCX ZIP members.

- [ ] Step 5: Implement random storage

Create the upload root, generate uuid4().hex plus the original safe suffix, write the bytes, calculate SHA-256, and return a relative path. Never put the original filename into the storage path.

- [ ] Step 6: Run tests, ignore artifacts, and commit

    python -m pytest backend/tests/test_resume_files.py -q

Expected: all validation and storage tests pass. Add data/uploads/ to .gitignore, verify generated files are not listed, then run:

    git add backend/app/resume_files.py backend/app/config.py backend/tests/test_resume_files.py .gitignore
    git commit -m "feat: validate and store resume uploads safely"

## Task 3: Persist parsed sources and expose the API

**Files:**
- Modify: backend/app/models.py
- Modify: backend/app/schemas.py
- Modify: backend/app/services.py
- Modify: backend/app/main.py
- Modify: backend/tests/conftest.py
- Modify: backend/tests/test_api.py

**Interfaces:**
- Produces POST /api/resumes/parse with multipart field file.
- Produces ResumeParseResponse with resume_id, source_type, original_filename, unit_count, character_count, extracted_text, and warnings.
- Changes ProfileCreate to keep required resume_text and accept resume_id: str | None = None.
- Changes create_app(database_url: str | None = None, upload_root: Path | None = None) -> FastAPI.

- [ ] Step 1: Write failing API and persistence tests

Upload generated files with:

    files = {"file": ("resume.pdf", pdf_bytes, "application/pdf")}
    response = client.post("/api/resumes/parse", files=files)
    assert response.status_code == 200
    body = response.json()
    assert body["source_type"] == "pdf"
    assert body["extracted_text"]
    assert body["character_count"] == len(body["extracted_text"])

Assert one Resume, one ResumeSource, and one stored file. Add tests for 413, 415, 422, profile reuse with edited resume_text, missing resume_id, and non-local owner. Preserve the existing pasted profile test.

- [ ] Step 2: Run API tests and verify failure

    python -m pytest backend/tests/test_api.py -q

Expected: upload route and source persistence tests fail.

- [ ] Step 3: Add the additive ResumeSource model

Add a table with id, resume_id, source_type, original_filename, stored_path, file_size, file_hash, unit_count, extracted_text, parse_status, warnings_json, and created_at. Use a foreign key to resumes.id and do not change existing Resume columns.

- [ ] Step 4: Add schemas and error handlers

Add ResumeParseResponse and resume_id to ProfileCreate. Add handlers for upload errors, NoExtractableTextError, InvalidDocumentError, and ResumeOwnerConflictError, returning {"detail": message, "code": error_code} without stack traces or local paths.

- [ ] Step 5: Implement parse-and-store service

Add:

    def parse_and_store_resume(
        db: Session,
        *,
        file_bytes: bytes,
        original_filename: str,
        content_type: str | None,
        upload_root: Path,
    ) -> dict:
        validated = validate_resume_upload(
            original_filename, content_type, file_bytes
        )
        parser = ResumeParserRegistry.for_file(
            original_filename, content_type
        )
        parsed = parser.parse(file_bytes, original_filename, content_type)
        stored = store_resume_file(
            file_bytes, validated.source_type, upload_root
        )
        user = db.get(User, LOCAL_USER_ID)
        if user is None:
            user = User(id=LOCAL_USER_ID)
            db.add(user)
            db.flush()
        resume = Resume(
            id=str(uuid4()),
            user_id=user.id,
            resume_text=parsed.text,
            text_hash=hashlib.sha256(parsed.text.encode("utf-8")).hexdigest(),
        )
        db.add(resume)
        db.flush()
        db.add(ResumeSource(
            id=str(uuid4()),
            resume_id=resume.id,
            source_type=validated.source_type,
            original_filename=original_filename,
            stored_path=str(stored.relative_path),
            file_size=len(file_bytes),
            file_hash=stored.file_hash,
            unit_count=parsed.unit_count,
            extracted_text=parsed.text,
            parse_status="parsed",
            warnings_json=json.dumps(parsed.warnings, ensure_ascii=False),
        ))
        db.commit()
        return {
            "resume_id": resume.id,
            "source_type": parsed.source_type,
            "original_filename": original_filename,
            "unit_count": parsed.unit_count,
            "character_count": len(parsed.text),
            "extracted_text": parsed.text,
            "warnings": parsed.warnings,
        }

Validate, select the adapter, parse before storing, ensure local-user, create Resume with extracted text/hash, store the random file, create ResumeSource(parse_status="parsed"), commit, and return response fields. If a later step fails, remove a file written before commit.

- [ ] Step 6: Implement the upload route

Make POST /api/resumes/parse async, read through read_upload_bytes(file, MAX_RESUME_UPLOAD_BYTES), call the service, and set app.state.upload_root = upload_root or DEFAULT_UPLOAD_ROOT.

- [ ] Step 7: Reuse parsed resumes in create_profile

Without resume_id, preserve the current new-Resume path. With resume_id, load and ownership-check the existing resume, update its final text and SHA-256, and attach the new ResumeProject to it. Do not create a duplicate Resume.

- [ ] Step 8: Run API tests and commit

    python -m pytest backend/tests/test_api.py -q
    git add backend/app/models.py backend/app/schemas.py backend/app/services.py backend/app/main.py backend/tests/conftest.py backend/tests/test_api.py
    git commit -m "feat: expose resume parsing upload api"

Expected: upload, persistence, error, reuse, and existing interview API tests pass.

## Task 4: Add the frontend upload and confirmation flow

**Files:**
- Modify: frontend/lib/api.ts
- Modify: frontend/app/page.tsx

**Interfaces:**
- Produces parseResume(file: File) -> Promise<ResumeParseResponse>.
- createProfile accepts { resume_text: string; resume_id?: string; project: ProjectInput }.
- The page stores resumeId only for the currently displayed parsed draft.

- [ ] Step 1: Update the API client for multipart

Add the response type and implement the upload request with FormData. Do not set Content-Type: application/json for this request; let the browser add the multipart boundary. Update the shared request helper so JSON headers are added only for JSON string bodies.

    export function parseResume(file: File) {
      const body = new FormData();
      body.append("file", file);
      return request<ResumeParseResponse>("/api/resumes/parse", {
        method: "POST",
        body,
      });
    }

- [ ] Step 2: Add the upload control

Add a file input with accept=".pdf,.docx,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document" above the textarea, plus a PDF / DOCX label and parsing state.

- [ ] Step 3: Connect success and failure states

If existing text is non-empty, ask window.confirm("上传文件会替换当前简历文本，是否继续？"). On success set resumeId, resumeText, filename, format, and unit count. On failure keep current text and display the API error. Disable repeated uploads while parsing.

- [ ] Step 4: Submit editable final text

Pass resume_id: resumeId || undefined and the current textarea value to createProfile. Keep all eight project fields and the existing createSession navigation unchanged.

- [ ] Step 5: Build and commit

    npm --prefix frontend run build
    git add frontend/lib/api.ts frontend/app/page.tsx
    git commit -m "feat: add resume pdf docx upload flow"

Expected: the production build succeeds and existing routes remain available.

## Task 5: Regression verification and runbook update

**Files:**
- Modify: README.md
- Do not modify the existing untracked .vscode/ directory.

- [ ] Step 1: Run the complete backend suite

    python -m pytest backend/tests -q

Expected: all existing and new backend tests pass.

- [ ] Step 2: Run the frontend build

    npm --prefix frontend run build

Expected: exit code 0.

- [ ] Step 3: Run a local HTTP smoke test

Start the backend with python -m uvicorn app.main:app --app-dir backend --port 8000 and the frontend with npm --prefix frontend run dev. Upload one text PDF and one DOCX, confirm text replacement, edit the text, fill the project fields, start the interview, answer one question, refresh, and open the report.

- [ ] Step 4: Update the README runbook

Document supported PDF/DOCX formats, text-only limitation, 10 MiB limit, local data/uploads/ storage, and the flow “upload → edit text → confirm project → start interview”. State that scanned PDF/image OCR is not supported.

- [ ] Step 5: Inspect final diff and commit documentation

    git diff --check
    git status --short --branch
    git log --oneline -8

Confirm no upload artifacts, database files, or unrelated .vscode/ files were added. Then run:

    git add README.md
    git commit -m "docs: document resume upload flow"
    python -m pytest backend/tests -q
    npm --prefix frontend run build

Expected: clean diff check, intended files only, backend tests pass, and frontend build passes.
