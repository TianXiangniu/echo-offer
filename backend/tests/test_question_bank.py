from app.question_bank import (
    FOUNDATION_QUESTION_GROUPS,
    ProjectQuestionData,
    build_foundation_specs,
    build_question_specs,
)


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


def test_foundation_specs_are_balanced_and_exclude_project_questions():
    import random

    specs = build_foundation_specs(rng=random.Random(7))

    assert len(specs) == 5
    assert [spec.order for spec in specs] == [1, 2, 3, 4, 5]
    assert all(
        not spec.knowledge_point_id.startswith(("project.", "behavioral."))
        for spec in specs
    )
    assert all(
        spec.knowledge_point_id in group
        for spec, group in zip(specs, FOUNDATION_QUESTION_GROUPS, strict=True)
    )


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


def test_every_knowledge_point_has_parallel_template_pool():
    from app.question_bank import QUESTION_TEMPLATES

    assert len(QUESTION_TEMPLATES) == 15
    for knowledge_point_id, pool in QUESTION_TEMPLATES.items():
        assert len(pool) >= 2, knowledge_point_id
        assert len({template.template_id for template in pool}) == len(pool)
        assert all(len(template.signals) >= 2 for template in pool)
        assert all(template.reference_facts for template in pool)


def test_default_specs_pick_first_template_and_carry_template_id():
    specs = build_question_specs()
    fixed = [spec for spec in specs if spec.template_id]
    assert len(fixed) == 5
    assert all(spec.template_id.endswith("#v1") for spec in fixed)


def test_excluded_template_ids_are_avoided_with_rng():
    import random as random_module

    from app.question_bank import DEFAULT_FIXED_KNOWLEDGE_POINTS

    excluded = {f"{point_id}#v1" for point_id in DEFAULT_FIXED_KNOWLEDGE_POINTS}
    specs = build_question_specs(excluded_template_ids=excluded, rng=random_module.Random(42))

    fixed = [spec for spec in specs if spec.template_id]
    assert len(fixed) == 5
    assert len({spec.knowledge_point_id for spec in fixed}) == 5
    assert all(spec.template_id not in excluded for spec in fixed)


def test_rng_sampling_keeps_anchors_and_distinct_knowledge_points():
    import random as random_module

    specs = build_question_specs(rng=random_module.Random(7))
    fixed = [spec for spec in specs if spec.template_id]

    assert len({spec.knowledge_point_id for spec in fixed}) == 5
    assert [spec.is_anchor for spec in specs] == [
        True, False, False, True, False, False, True, False,
    ]
    from app.question_bank import ANCHOR_KNOWLEDGE_POINTS
    assert fixed[0].knowledge_point_id in ANCHOR_KNOWLEDGE_POINTS
    assert fixed[3].knowledge_point_id in ANCHOR_KNOWLEDGE_POINTS


def test_debug_coding_question_carries_non_default_rubric_weights():
    from app.question_bank import QUESTION_TEMPLATES, QuestionSpec
    from app.rubrics import build_rubric

    template = QUESTION_TEMPLATES["coding.debug_tool_call"][0]
    spec = QuestionSpec(
        order=4, category="reliability", is_anchor=False,
        prompt=template.prompt,
        knowledge_point_id="coding.debug_tool_call",
        rubric_version="alpha-local-v1",
        signals=template.signals,
        reference_facts=template.reference_facts,
        template_id=template.template_id,
        rubric_weights=template.rubric_weights,
    )
    rubric = build_rubric(spec)
    weights = {item.rubric_id: item.weight for item in rubric.items}
    assert weights["correctness"] == 1.5
    assert weights["scenario"] == 0.5
    assert weights["mechanism"] == 1.0


def test_rng_layout_always_includes_one_practical_slot():
    import random as random_module

    from app.question_bank import PRACTICAL_KNOWLEDGE_POINTS, category_for_kp

    for seed in range(5):
        specs = build_question_specs(rng=random_module.Random(seed))
        fixed = [spec for spec in specs if spec.template_id]
        last = fixed[4]
        assert last.knowledge_point_id in PRACTICAL_KNOWLEDGE_POINTS, seed
        assert category_for_kp(last.knowledge_point_id) in {"design", "coding", "behavioral"}
        assert len({spec.knowledge_point_id for spec in fixed}) == 5


def test_behavioral_question_overrides_rubric_criteria():
    from app.question_bank import QUESTION_TEMPLATES, QuestionSpec
    from app.rubrics import build_rubric

    template = QUESTION_TEMPLATES["behavioral.project_conflict"][0]
    spec = QuestionSpec(
        order=4, category="behavioral", is_anchor=False,
        prompt=template.prompt,
        knowledge_point_id="behavioral.project_conflict",
        rubric_version="alpha-local-v1",
        signals=template.signals,
        reference_facts=template.reference_facts,
        template_id=template.template_id,
        criteria_override=template.criteria_override,
    )
    rubric = build_rubric(spec)
    by_id = {item.rubric_id: item for item in rubric.items}
    assert by_id["scenario"].criterion == "有具体情境、角色和冲突焦点"
    assert by_id["correctness"].criterion == "叙述真实且具体，能自洽"
    # 无覆写的题保持默认 criterion
    default = build_rubric(build_question_specs()[3])
    assert {item.rubric_id: item for item in default.items}["scenario"].criterion == (
        "是否结合具体场景、数据或实例分析；有真实细节而非泛泛而谈"
    )
