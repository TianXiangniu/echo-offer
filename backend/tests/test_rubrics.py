from app.question_bank import ProjectQuestionData, build_question_specs
from app.rubrics import build_rubric, rubric_from_dict, rubric_to_dict


def test_default_question_has_frozen_four_item_rubric():
    rubric = build_rubric(build_question_specs()[0])

    assert rubric.version == "alpha-local-v1"
    assert [item.rubric_id for item in rubric.items] == [
        "correctness",
        "mechanism",
        "scenario",
        "engineering",
    ]
    assert all(item.criterion for item in rubric.items)
    assert all(item.weight == 1.0 for item in rubric.items)


def test_custom_project_rubric_does_not_copy_resume_text_into_reference_facts():
    resume_text = "绝不应该进入评分上下文的简历内容"
    question = build_question_specs(
        [
            ProjectQuestionData(
                prompt=f"请分析项目：{resume_text}",
                knowledge_point_id="project.custom",
                signals=("召回", "延迟"),
            ),
            ProjectQuestionData(
                prompt="请解释方案取舍",
                knowledge_point_id="project.tradeoff",
                signals=("方案", "取舍"),
            ),
            ProjectQuestionData(
                prompt="请说明如何验证",
                knowledge_point_id="project.evaluation",
                signals=("指标", "复现"),
            ),
        ]
    )[0]

    rubric = build_rubric(question)

    assert all(resume_text not in fact for item in rubric.items for fact in item.reference_facts)


def test_fixed_question_reference_facts_flow_into_snapshot():
    specs = build_question_specs()
    retrieval = next(spec for spec in specs if spec.knowledge_point_id == "rag.retrieval_diagnosis")

    rubric = build_rubric(retrieval)

    assert rubric.reference_facts
    assert any("分桶" in fact for fact in rubric.reference_facts)


def test_rubric_snapshot_reference_facts_round_trip():
    specs = build_question_specs()
    tooling = next(spec for spec in specs if spec.knowledge_point_id == "agent_runtime.tool_calling")

    restored = rubric_from_dict(rubric_to_dict(build_rubric(tooling)))

    assert restored.reference_facts == build_rubric(tooling).reference_facts


def test_legacy_rubric_snapshot_without_reference_facts_still_parses():
    restored = rubric_from_dict(
        {
            "version": "alpha-local-v1",
            "items": [
                {"rubric_id": "correctness", "criterion": "是否正确"},
            ],
        }
    )

    assert restored.reference_facts == ()


def test_custom_project_knowledge_point_without_mapping_has_no_reference_facts():
    specs = build_question_specs(
        [
            ProjectQuestionData("项目题一", "project.custom.one", ("职责", "目标")),
            ProjectQuestionData("项目题二", "project.tradeoff", ("方案", "取舍")),
            ProjectQuestionData("项目题三", "project.evaluation", ("评估", "指标")),
        ]
    )

    assert all(build_rubric(spec).reference_facts == () for spec in specs[:3])
