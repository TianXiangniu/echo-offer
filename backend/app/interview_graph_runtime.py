"""Small LangGraph runtime helpers used by the interview workflow."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import TypedDict

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt


class _ProbeState(TypedDict, total=False):
    value: str
    answer: str


def create_checkpointer(database_path: str) -> SqliteSaver:
    """Create a synchronous SQLite checkpointer for one app process."""

    Path(database_path).parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(database_path, check_same_thread=False)
    return SqliteSaver(connection)


def close_checkpointer(checkpointer: SqliteSaver) -> None:
    """Close the SQLite connection owned by a checkpointer."""

    checkpointer.conn.close()


def graph_config(session_id: str) -> dict[str, dict[str, str]]:
    """Build the stable LangGraph config for an interview session."""

    return {"configurable": {"thread_id": session_id}}


def build_interrupt_probe(checkpointer: SqliteSaver):
    """Build a tiny graph used to verify checkpoint/restart semantics."""

    def pause_for_answer(state: _ProbeState) -> dict[str, str]:
        answer = interrupt({"question": "请继续"})
        return {"answer": str(answer)}

    graph = StateGraph(_ProbeState)
    graph.add_node("pause", pause_for_answer)
    graph.add_edge(START, "pause")
    graph.add_edge("pause", END)
    return graph.compile(checkpointer=checkpointer)
