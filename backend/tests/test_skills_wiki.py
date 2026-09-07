"""知识点 Wiki：种子、API 与生成管线测试。"""

import json

from app.models import SkillWiki
from app.skills_flow import get_skill_detail, list_skills
from tests.conftest import FakeAssessmentProvider, create_test_session


def test_seeds_create_wikis_with_facts_and_fixed_names(client):
    with client.app.state.session_factory() as db:
        skills = list_skills(db)
        detail = get_skill_detail(db, "rag.retrieval_diagnosis")
    by_id = {s["skill_id"]: s for s in skills}
    assert len(skills) >= 15
    assert by_id["coding.debug_tool_call"]["name"] == "实战找问题"
    sections = detail["sections"]
    assert sections["definition"]
    assert any("分桶" in point for point in sections["key_points"])
    assert len(sections["pitfalls"]) >= 2
    # 金标集里有该知识点的 3/4 级示例
    assert sections["examples"]


def test_seed_is_idempotent_and_preserves_deep_dive(client):
    with client.app.state.session_factory() as db:
        wiki = db.get(SkillWiki, "rag.retrieval_diagnosis")
        wiki.content_json = json.dumps(
            {**json.loads(wiki.content_json), "deep_dive": {"mechanism": "已有深讲"}}
        )
        wiki.has_deep_dive = True
        db.commit()

        from app.skills_seed import ensure_skill_wiki_seeds

        ensure_skill_wiki_seeds(db)
        db.refresh(wiki)
        content = json.loads(wiki.content_json)
        assert content["deep_dive"]["mechanism"] == "已有深讲"
        assert wiki.has_deep_dive is True


def test_study_marking_and_list_reflects_it(ai_client):
    session_id, questions = create_test_session(ai_client)
    for index, question in enumerate(questions, start=1):
        ai_client.post(
            f"/api/sessions/{session_id}/answers",
            json={
                "question_id": question["id"],
                "client_submission_id": f"study-{index}",
                "status": "submitted",
                "answer_text": f"第 {index} 题：机制边界取舍。",
            },
        )
    ai_client.post(f"/api/sessions/{session_id}/assessment")
    ai_client.post("/api/skills/agent_runtime.tool_calling/study")
    skills = ai_client.get("/api/skills").json()["skills"]
    by_id = {s["skill_id"]: s for s in skills}
    # 已考知识点必须显示掌握度；未考到的为 None（动态抽题，不能假设固定知识点）
    assert by_id[questions[0]["knowledge_point_id"]]["level"] is not None
    assert by_id["agent_runtime.tool_calling"]["studied"] is True


def test_wiki_generate_with_fake_provider(ai_client):
    create_test_session(ai_client)

    class FakeWikiProvider(FakeAssessmentProvider):
        model_name = "fake-model"

        def generate_skill_wiki(self, payload):
            assert payload["name"]
            assert payload["key_points"]
            return {
                "mechanism": "这个知识点的机制是：先分桶定位，再分层修复。",
                "personal_focus": "你上次的回答跳过了评测集回归，补上它。",
                "pitfalls_extra": ["只看单次样本就下结论。"],
            }

    response = ai_client.post("/api/skills/rag.retrieval_diagnosis/wiki/generate")
    assert response.status_code == 503  # ai_client 未注入 wiki 能力的 provider

    from app.main import create_app
    from fastapi.testclient import TestClient
    import tempfile, pathlib

    tmp = pathlib.Path(tempfile.mkdtemp())
    app = create_app(
        f"sqlite:///{tmp / 'wiki.db'}",
        upload_root=tmp / "uploads",
        assessment_provider=FakeWikiProvider(),
    )
    with TestClient(app) as custom:
        create_test_session(custom)
        result = custom.post("/api/skills/rag.retrieval_diagnosis/wiki/generate")
        assert result.status_code == 200
        assert "分桶定位" in result.json()["deep_dive"]["mechanism"]

        detail = custom.get("/api/skills/rag.retrieval_diagnosis").json()
        assert detail["has_deep_dive"] is True
        assert detail["sections"]["deep_dive"]["personal_focus"]


def test_skill_detail_includes_related_questions_and_recent_answer(ai_client):
    create_test_session(ai_client)
    detail = ai_client.get("/api/skills/rag.retrieval_diagnosis").json()
    assert detail["related_questions"]
    # create_test_session 只答了默认题，rag 知识点未必有回答——字段存在即可
    assert "recent_answer" in detail