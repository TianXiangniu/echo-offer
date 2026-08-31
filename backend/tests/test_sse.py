import json

from app.sse import format_sse_event


def test_format_sse_event_serializes_utf8_json_and_blank_line():
    result = format_sse_event("stage", {"stage": "analyzing", "message": "正在分析项目"})

    lines = result.splitlines()
    assert lines[0] == "event: stage"
    assert json.loads(lines[1].removeprefix("data: ")) == {
        "stage": "analyzing",
        "message": "正在分析项目",
    }
    assert result.endswith("\n\n")
