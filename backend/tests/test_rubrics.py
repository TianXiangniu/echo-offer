from app.question_bank import ProjectQuestionData, build_question_specs
from app.rubrics import build_rubric


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
