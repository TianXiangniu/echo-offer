from app.question_bank import build_question_specs


def test_question_bank_has_three_two_three_shape_and_three_anchors():
    specs = build_question_specs()

    assert len(specs) == 8
    assert [spec.category for spec in specs].count("project") == 3
    assert [spec.category for spec in specs].count("agent") == 3
    assert [spec.category for spec in specs].count("reliability") == 2
    assert [spec.is_anchor for spec in specs[:3]] == [True, True, True]
    assert sum(spec.is_anchor for spec in specs) == 3


def test_question_bank_specs_are_versioned_and_ordered():
    specs = build_question_specs()

    assert [spec.order for spec in specs] == list(range(1, 9))
    assert len({spec.knowledge_point_id for spec in specs}) == 8
    assert all(spec.rubric_version == "alpha-local-v1" for spec in specs)
    assert all(len(spec.signals) >= 2 for spec in specs)
