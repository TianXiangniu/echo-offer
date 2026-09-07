from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import AsyncIterator
from pathlib import Path
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .config import LOCAL_USER_ID, MAX_ANALYSIS_RESUME_CHARS, SILICONFLOW_MODEL
from .models import (
    InterviewTarget,
    Resume,
    ResumeProject,
    ResumeProjectAnalysis,
    ResumeProjectQuestion,
    ResumeSource,
    User,
)
from .project_analysis import validate_analysis_evidence
from .providers import ProjectAnalysisProvider, ProjectAnalysisProviderError
from .resume_files import (
    StoredResumeFile,
    ValidatedResumeFile,
    store_resume_file,
    validate_resume_upload,
)
from .resume_parsers import ResumeParserRegistry
from .schemas import ProfileCreate
from .sse import format_sse_event
from .workflow_common import (
    ConflictError,
    NotFoundError,
    ProjectAnalysisError,
    ResumeNotFoundError,
    ResumeOwnerConflictError,
)

def _reconcile_confirmed_analysis_snapshot(
    analysis_json: str,
    confirmed_project: dict,
) -> str:
    snapshot = json.loads(analysis_json or "{}")

    project_snapshot = snapshot.get("project") or {}
    project_snapshot["core"] = dict(confirmed_project)
    snapshot["project"] = project_snapshot
    if not snapshot.get("schema_version"):
        snapshot["schema_version"] = "project-analysis-v2"
    return json.dumps(snapshot, ensure_ascii=False, sort_keys=True)

def create_profile(db: Session, payload: ProfileCreate) -> dict:
    user = db.get(User, LOCAL_USER_ID)
    if user is None:
        user = User(id=LOCAL_USER_ID)
        db.add(user)
        db.flush()

    resume_text_hash = hashlib.sha256(payload.resume_text.encode("utf-8")).hexdigest()
    if payload.resume_id is None:
        resume = Resume(
            id=str(uuid4()),
            user_id=user.id,
            resume_text=payload.resume_text,
            text_hash=resume_text_hash,
        )
        db.add(resume)
        db.flush()
    else:
        resume = db.get(Resume, payload.resume_id)
        if resume is None:
            raise ResumeNotFoundError("resume not found")
        if resume.user_id != user.id:
            raise ResumeOwnerConflictError("resume does not belong to the current user")
        resume.resume_text = payload.resume_text
        resume.text_hash = resume_text_hash

    analysis = None
    if payload.analysis_id is not None:
        analysis = db.get(ResumeProjectAnalysis, payload.analysis_id)
        if analysis is None:
            raise NotFoundError("project analysis not found")
        if analysis.user_id != user.id or analysis.resume_id != resume.id:
            raise ConflictError("project analysis does not belong to the resume")
        if analysis.status != "draft":
            raise ConflictError("project analysis is not a draft")
        if payload.project_questions is None or len(payload.project_questions) != 3:
            raise ConflictError("exactly three project questions are required")
    elif payload.project_questions is not None:
        raise ConflictError("project_questions require analysis_id")

    max_version = db.scalar(
        select(func.max(ResumeProject.project_version)).join(Resume).where(Resume.user_id == user.id)
    )
    project = ResumeProject(
        id=str(uuid4()),
        resume_id=resume.id,
        project_version=(max_version or 0) + 1,
        analysis_id=analysis.id if analysis else None,
        **payload.project.model_dump(),
    )
    db.add(project)
    db.flush()

    if analysis is not None:
        original_questions = json.loads(analysis.analysis_json).get("questions", [])
        for index, question in enumerate(payload.project_questions or [], start=1):
            source = (
                "model"
                if index <= len(original_questions)
                and question.model_dump() == original_questions[index - 1]
                else "user_edited"
            )
            db.add(
                ResumeProjectQuestion(
                    id=str(uuid4()),
                    resume_project_id=project.id,
                    order=index,
                    prompt=question.prompt,
                    knowledge_point_id=question.knowledge_point_id,
                    signals_json=json.dumps(question.signals, ensure_ascii=False),
                    source=source,
                )
            )
        analysis.analysis_json = _reconcile_confirmed_analysis_snapshot(
            analysis.analysis_json,
            payload.project.model_dump(),
        )
        analysis.status = "confirmed"

    target = InterviewTarget(
        id=str(uuid4()),
        user_id=user.id,
        direction="agent_application_rag",
        level="one_to_three_years",
        language="zh_cn",
        company_type="unspecified",
        target_title="Agent 应用工程师",
        jd_text="",
    )
    db.add(target)
    db.commit()
    return {
        "profile_id": project.id,
        "user_id": user.id,
        "project_version": project.project_version,
        "resume_text_hash": resume_text_hash,
        "direction": target.direction,
        "level": target.level,
        "language": target.language,
    }

def parse_and_store_resume(
    db: Session,
    *,
    file_bytes: bytes,
    original_filename: str,
    content_type: str | None,
    upload_root: Path,
) -> dict:
    validated: ValidatedResumeFile = validate_resume_upload(
        original_filename, content_type, file_bytes
    )
    parser = ResumeParserRegistry.for_file(original_filename, content_type)
    parsed = parser.parse(file_bytes, original_filename, content_type)

    user = db.get(User, LOCAL_USER_ID)
    if user is None:
        user = User(id=LOCAL_USER_ID)
        db.add(user)
        db.flush()

    stored: StoredResumeFile | None = None
    try:
        stored = store_resume_file(file_bytes, validated.source_type, upload_root)
        resume = Resume(
            id=str(uuid4()),
            user_id=user.id,
            resume_text=parsed.text,
            text_hash=hashlib.sha256(parsed.text.encode("utf-8")).hexdigest(),
        )
        db.add(resume)
        db.flush()
        db.add(
            ResumeSource(
                id=str(uuid4()),
                resume_id=resume.id,
                source_type=parsed.source_type,
                original_filename=validated.original_filename,
                stored_path=str(stored.relative_path),
                file_size=len(file_bytes),
                file_hash=stored.file_hash,
                unit_count=parsed.unit_count,
                extracted_text=parsed.text,
                parse_status="parsed",
                warnings_json=json.dumps(parsed.warnings, ensure_ascii=False),
            )
        )
        db.commit()
    except Exception:
        db.rollback()
        if stored is not None:
            (upload_root / stored.relative_path).unlink(missing_ok=True)
        raise

    return {
        "resume_id": resume.id,
        "source_type": parsed.source_type,
        "original_filename": validated.original_filename,
        "unit_count": parsed.unit_count,
        "character_count": len(parsed.text),
        "extracted_text": parsed.text,
        "warnings": parsed.warnings,
    }

def analyze_resume_project(
    db: Session,
    provider: ProjectAnalysisProvider,
    resume_id: str,
    resume_text: str,
) -> dict:
    resume = db.get(Resume, resume_id)
    if resume is None:
        raise ResumeNotFoundError("resume not found")
    if resume.user_id != LOCAL_USER_ID:
        raise ResumeOwnerConflictError("resume does not belong to the current user")
    if not resume_text.strip():
        raise ProjectAnalysisError("resume_text_empty", "简历文本不能为空", 422)
    if len(resume_text) > MAX_ANALYSIS_RESUME_CHARS:
        raise ProjectAnalysisError("resume_text_too_long", "简历文本过长", 413)

    text_hash = hashlib.sha256(resume_text.encode("utf-8")).hexdigest()
    analysis = ResumeProjectAnalysis(
        id=str(uuid4()),
        resume_id=resume.id,
        user_id=resume.user_id,
        resume_text_hash=text_hash,
        model_name=SILICONFLOW_MODEL,
        provider_name="siliconflow",
        status="draft",
        analysis_json="{}",
    )
    db.add(analysis)
    try:
        result = provider.analyze(resume_text)
        result = validate_analysis_evidence(result, resume_text)
        analysis.analysis_json = json.dumps(
            result.model_dump(), ensure_ascii=False, sort_keys=True
        )
        db.commit()
    except ProjectAnalysisProviderError as exc:
        analysis.status = "failed"
        analysis.error_code = exc.code
        db.commit()
        raise
    except ValueError as exc:
        analysis.status = "failed"
        analysis.error_code = "invalid_model_response"
        db.commit()
        raise ProjectAnalysisError("invalid_model_response", "模型返回内容无法确认", 502) from exc

    return {
        "analysis_id": analysis.id,
        "resume_id": resume.id,
        "resume_text_hash": text_hash,
        "status": analysis.status,
        **result.model_dump(),
    }

async def stream_resume_project_analysis(
    db: Session,
    provider: ProjectAnalysisProvider,
    resume_id: str,
    resume_text: str,
    *,
    heartbeat_interval_seconds: float = 10.0,
) -> AsyncIterator[str]:
    resume = db.get(Resume, resume_id)
    if resume is None:
        yield format_sse_event(
            "error", {"code": "resume_not_found", "message": "resume not found"}
        )
        return
    if resume.user_id != LOCAL_USER_ID:
        yield format_sse_event(
            "error",
            {
                "code": "resume_owner_conflict",
                "message": "resume does not belong to the current user",
            },
        )
        return
    if not resume_text.strip():
        yield format_sse_event(
            "error", {"code": "resume_text_empty", "message": "简历文本不能为空"}
        )
        return
    if len(resume_text) > MAX_ANALYSIS_RESUME_CHARS:
        yield format_sse_event(
            "error", {"code": "resume_text_too_long", "message": "简历文本过长"}
        )
        return

    text_hash = hashlib.sha256(resume_text.encode("utf-8")).hexdigest()
    analysis = ResumeProjectAnalysis(
        id=str(uuid4()),
        resume_id=resume.id,
        user_id=resume.user_id,
        resume_text_hash=text_hash,
        model_name=SILICONFLOW_MODEL,
        provider_name="siliconflow",
        status="draft",
        analysis_json="{}",
    )
    db.add(analysis)
    db.flush()
    yield format_sse_event(
        "stage", {"stage": "received", "message": "已接收简历"}
    )
    yield format_sse_event(
        "stage", {"stage": "analyzing", "message": "正在分析项目"}
    )

    task = asyncio.create_task(asyncio.to_thread(provider.analyze, resume_text))
    try:
        while not task.done():
            finished, _ = await asyncio.wait(
                (task,), timeout=heartbeat_interval_seconds
            )
            if not finished:
                yield format_sse_event("heartbeat", {"stage": "analyzing"})

        result = task.result()
        yield format_sse_event(
            "stage", {"stage": "validating", "message": "正在校验证据"}
        )
        result = validate_analysis_evidence(result, resume_text)
        analysis.analysis_json = json.dumps(
            result.model_dump(), ensure_ascii=False, sort_keys=True
        )
        db.commit()
        response = {
            "analysis_id": analysis.id,
            "resume_id": resume.id,
            "resume_text_hash": text_hash,
            "status": analysis.status,
            **result.model_dump(),
        }
        yield format_sse_event(
            "stage", {"stage": "completed", "message": "分析完成"}
        )
        yield format_sse_event("result", response)
        yield format_sse_event("done", {"status": "completed"})
    except asyncio.CancelledError:
        task.cancel()
        raise
    except ProjectAnalysisProviderError as exc:
        analysis.status = "failed"
        analysis.error_code = exc.code
        db.commit()
        yield format_sse_event("error", {"code": exc.code, "message": str(exc)})
    except ValueError:
        analysis.status = "failed"
        analysis.error_code = "invalid_model_response"
        db.commit()
        yield format_sse_event(
            "error",
            {
                "code": "invalid_model_response",
                "message": "模型返回内容无法确认",
            },
        )

