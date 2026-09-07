import json

import pytest
from sqlalchemy import func, select

from app.database import create_database
from app.interview_flow import create_session, get_session_view
from app.models import (
    AnswerAttempt,
    InterviewQuestion,
    InterviewSession,
    InterviewTarget,
    ProjectDialog,
    Resume,
    ResumeProject,
    User,
)
from app.workflow_common import ConflictError
from app.interview_graph_projection import project_graph_event


def _session_db(tmp_path, *, mode="graph", with_session=True):
    _, factory = create_database(f"sqlite:///{tmp_path / 'projection.db'}")
    with factory() as db:
        user = User(id="user-1")
        resume = Resume(
            id="resume-1", user_id=user.id, resume_text="简历", text_hash="hash"
        )
        project = ResumeProject(
            id="project-1",
            resume_id=resume.id,
            project_name="RAG Agent",
            background_goal="降本",
            tech_stack="Python",
            responsibilities="检索",
            core_solution="混合检索",
            engineering_challenges="延迟",
            failure_improvements="降级",
            quantified_results="命中率提升",
        )
        target = InterviewTarget(id="target-1", user_id=user.id)
        session = InterviewSession(
            id="session-1",
            user_id=user.id,
            resume_project_id=project.id,
            target_id=target.id,
            mode=mode,
            stage="planning",
            status="in_progress",
        )
        db.add(user)
        db.flush()
        db.add(resume)
        db.flush()
        db.add(project)
        db.add(target)
        db.flush()
        if with_session:
            db.add(session)
        db.commit()
    return factory, session.id if with_session else None


def _question_event(step="node-1", text="你负责了哪部分？"):
    return {
        "session_id": "session-1",
        "graph_step_id": step,
        "event_kind": "question_ready",
        "payload": {
            "node_id": "node-1",
            "kind": "project",
            "text": text,
            "order": 0,
        },
    }


def test_duplicate_graph_event_does_not_duplicate_question(tmp_path):
    factory, session_id = _session_db(tmp_path)
    event = _question_event()
    with factory() as db:
        assert project_graph_event(db, event) is True
        assert project_graph_event(db, event) is False
        assert db.scalar(
            select(func.count(InterviewQuestion.id)).where(
                InterviewQuestion.session_id == session_id
            )
        ) == 1
        assert db.scalar(
            select(func.count(ProjectDialog.id)).where(
                ProjectDialog.session_id == session_id
            )
        ) == 1
        assert project_graph_event(db, _question_event(step="node-2")) is True
        assert db.scalar(
            select(func.count(InterviewQuestion.id)).where(
                InterviewQuestion.session_id == session_id
            )
        ) == 2


def test_same_graph_step_with_different_payload_is_conflict(tmp_path):
    factory, _ = _session_db(tmp_path)
    with factory() as db:
        project_graph_event(db, _question_event())
        changed = _question_event(text="你如何验证？")
        with pytest.raises(ConflictError, match="graph event payload conflict"):
            project_graph_event(db, changed)


def test_failed_projection_rolls_back_receipt(tmp_path):
    factory, session_id = _session_db(tmp_path)
    with factory() as db:
        with pytest.raises(ValueError, match="question text"):
            project_graph_event(
                db,
                {
                    "session_id": session_id,
                    "graph_step_id": "broken-1",
                    "event_kind": "question_ready",
                    "payload": {"node_id": "node-1"},
                },
            )
        from app.models import InterviewGraphEventReceipt

        assert db.scalar(
            select(func.count(InterviewGraphEventReceipt.id)).where(
                InterviewGraphEventReceipt.session_id == session_id
            )
        ) == 0


def test_answer_event_is_idempotent_and_legacy_view_is_readable(tmp_path):
    factory, session_id = _session_db(tmp_path)
    question_event = _question_event()
    with factory() as db:
        project_graph_event(db, question_event)
        view_before_answer = get_session_view(db, session_id)
        assert view_before_answer["current_question"]["prompt"] == "你负责了哪部分？"
        question_id = db.scalar(
            select(InterviewQuestion.id).where(
                InterviewQuestion.session_id == session_id
            )
        )
        answer_event = {
            "session_id": session_id,
            "graph_step_id": "answer-1",
            "event_kind": "candidate_answer",
            "payload": {
                "question_id": question_id,
                "client_submission_id": "client-1",
                "answer_text": "我负责检索链路。",
                "status": "submitted",
            },
        }
        assert project_graph_event(db, answer_event) is True
        assert project_graph_event(db, answer_event) is False
        assert db.scalar(
            select(func.count(AnswerAttempt.id)).where(
                AnswerAttempt.session_id == session_id
            )
        ) == 1

        view = get_session_view(db, session_id)
        assert view["mode"] == "graph"
        assert view["timeline"]
        assert any(item["role"] == "candidate" for item in view["timeline"])


def test_question_id_cannot_be_reused_by_another_session(tmp_path):
    factory, session_id = _session_db(tmp_path)
    with factory() as db:
        db.add(
            InterviewSession(
                id="session-2",
                user_id="user-1",
                resume_project_id="project-1",
                target_id="target-1",
                mode="graph",
                stage="planning",
                status="in_progress",
            )
        )
        db.commit()
        event = _question_event(step="node-1")
        event["payload"]["question_id"] = "shared-question"
        project_graph_event(db, event)
        with pytest.raises(ConflictError, match="belongs to another session"):
            project_graph_event(
                db,
                {
                    **event,
                    "session_id": "session-2",
                    "graph_step_id": "node-2",
                },
            )


def test_graph_session_creation_projects_initial_state_event(tmp_path):
    factory, _ = _session_db(tmp_path, with_session=False)
    with factory() as db:
        result = create_session(db, "project-1", mode="graph")
        from app.models import InterviewGraphEventReceipt

        assert db.scalar(
            select(InterviewGraphEventReceipt.event_kind).where(
                InterviewGraphEventReceipt.session_id == result["session_id"]
            )
        ) == "state_updated"


def test_graph_session_creation_rolls_back_if_bootstrap_projection_fails(tmp_path, monkeypatch):
    factory, _ = _session_db(tmp_path, with_session=False)

    def fail_projection(*args, **kwargs):
        raise RuntimeError("projection unavailable")

    monkeypatch.setattr("app.interview_graph_projection.project_graph_event", fail_projection)
    with factory() as db:
        with pytest.raises(RuntimeError, match="projection unavailable"):
            create_session(db, "project-1", mode="graph")
        db.rollback()
        assert db.scalar(select(func.count(InterviewSession.id))) == 0


def test_graph_checkpoint_state_maps_to_safe_session_view(tmp_path):
    factory, session_id = _session_db(tmp_path)
    state = {
        "session_id": session_id,
        "status": "awaiting_answer",
        "route": "insufficient",
        "current_node_index": 1,
        "plan": [
            {
                "node_id": "node-1",
                "kind": "project",
                "goal": "职责",
                "opening_question": "你负责了哪部分？",
            },
            {
                "node_id": "node-2",
                "kind": "architecture",
                "goal": "机制",
                "opening_question": "你如何设计？",
            },
        ],
        "current_question": {
            "node_id": "node-2",
            "text": "你如何设计？",
            "kind": "opening",
        },
        "coverage": {"node-1": ["context_ownership"]},
        "followups_used": {"node-2": 0},
        "messages": [],
    }
    with factory() as db:
        view = get_session_view(db, session_id, graph_state=state)
        assert view["status"] == "awaiting_answer"
        assert view["current_question"]["prompt"] == "你如何设计？"
        assert view["progress"] == {"completed": 1, "total": 2}
        assert [node["status"] for node in view["nodes"]] == ["covered", "active"]
        assert "coverage" not in json.dumps(view, ensure_ascii=False)


def test_graph_session_starts_without_legacy_questions(tmp_path):
    factory, _ = _session_db(tmp_path, with_session=False)
    with factory() as db:
        result = create_session(db, "project-1", mode="graph")
        session = db.get(InterviewSession, result["session_id"])
        assert session is not None
        assert session.mode == "graph"
        assert session.stage == "planning"
        assert result["questions"] == []
        assert db.scalar(
            select(func.count(InterviewQuestion.id)).where(
                InterviewQuestion.session_id == session.id
            )
        ) == 0
