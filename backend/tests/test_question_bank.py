from app.question_bank import ProjectQuestionData, build_question_specs


def test_question_bank_groups_question_categories_and_anchors():
    specs = build_question_specs()

    assert len(specs) == 8
    assert [spec.category for spec in specs] == [
        "project", "project", "project",
        "agent", "agent", "agent",
        "reliability", "reliability",
    ]
    assert [spec.is_anchor for spec in specs] == [
        True, False, False,
        True, False, False,
        True, False,
    ]
    assert sum(spec.is_anchor for spec in specs) == 3


def test_question_bank_specs_are_versioned_and_ordered():
    specs = build_question_specs()

    assert [spec.order for spec in specs] == list(range(1, 9))
    assert len({spec.knowledge_point_id for spec in specs}) == 8
    assert all(spec.rubric_version == "alpha-local-v1" for spec in specs)
    assert all(len(spec.signals) >= 2 for spec in specs)


def test_custom_project_questions_are_grouped_before_fixed_questions():
    custom = [
        ProjectQuestionData("项目题一", "project.custom.one", ("职责", "目标")),
        ProjectQuestionData("项目题二", "project.custom.two", ("方案", "取舍")),
        ProjectQuestionData("项目题三", "project.custom.three", ("评估", "指标")),
    ]

    specs = build_question_specs(custom)

    assert [spec.category for spec in specs] == [
        "project", "project", "project",
        "agent", "agent", "agent",
        "reliability", "reliability",
    ]
    assert [spec.prompt for spec in specs[:3]] == ["项目题一", "项目题二", "项目题三"]
    assert [spec.is_anchor for spec in specs] == [
        True, False, False,
        True, False, False,
        True, False,
    ]
