from typing import Literal


InterviewType = Literal["foundation", "project"]


def interview_type_from_mode(mode: str) -> InterviewType:
    return "project" if mode in {"graph", "dialog"} else "foundation"
