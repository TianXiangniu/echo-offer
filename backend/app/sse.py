import json


def format_sse_event(event_name: str, data: dict) -> str:
    serialized = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    return f"event: {event_name}\ndata: {serialized}\n\n"
