"""Helpers for turning provider responses into safe, parseable JSON values."""

from __future__ import annotations

import json
import re
from typing import Any


class ModelOutputError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def content_to_text(content: object) -> str:
    """Normalize the common OpenAI-compatible content shapes to text."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for part in content:
            if isinstance(part, str):
                parts.append(part)
            elif isinstance(part, dict):
                text = part.get("text")
                if isinstance(text, str):
                    parts.append(text)
        return "".join(parts)
    return ""


def _without_thinking(text: str) -> str:
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.IGNORECASE | re.DOTALL)
    return re.sub(r"<think>.*$", "", text, flags=re.IGNORECASE | re.DOTALL)


def parse_model_json(content: object) -> Any:
    """Parse one JSON value from provider text, tolerating wrappers around it."""
    text = _without_thinking(content_to_text(content)).strip()
    if not text:
        raise ModelOutputError("empty_model_response", "模型没有返回可解析内容")

    decoder = json.JSONDecoder()
    for index, character in enumerate(text):
        if character not in "[{":
            continue
        try:
            value, _ = decoder.raw_decode(text[index:])
        except json.JSONDecodeError:
            continue
        return value

    raise ModelOutputError("invalid_json", "模型返回内容不是完整 JSON")

