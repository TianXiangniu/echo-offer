import pytest

from app.model_output import ModelOutputError, content_to_text, parse_model_json


def test_parse_model_json_accepts_markdown_json_code_fence():
    assert parse_model_json('```json\n{"items": []}\n```') == {"items": []}


def test_parse_model_json_ignores_thinking_and_leading_explanation():
    content = "<think>先检查字段</think>下面是结果：\n{" + '"items": []}'

    assert parse_model_json(content) == {"items": []}


def test_content_to_text_accepts_openai_content_parts():
    content = [
        {"type": "text", "text": "{"},
        {"type": "text", "text": '"items": []}'},
    ]

    assert content_to_text(content) == '{"items": []}'
    assert parse_model_json(content) == {"items": []}


@pytest.mark.parametrize("content", [None, "", "not json", "{" + '"items": [' + "}"])
def test_parse_model_json_reports_specific_invalid_output(content):
    with pytest.raises(ModelOutputError) as error:
        parse_model_json(content)

    assert error.value.code in {"empty_model_response", "invalid_json"}

