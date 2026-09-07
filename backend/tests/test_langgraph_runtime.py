from langgraph.types import Command

from app.interview_graph_runtime import (
    build_interrupt_probe,
    close_checkpointer,
    create_checkpointer,
    graph_config,
)


def test_interrupted_graph_resumes_after_checkpoint_reopen(tmp_path):
    database_path = tmp_path / "langgraph-checkpoints.sqlite"
    config = graph_config("session-1")

    first_checkpointer = create_checkpointer(str(database_path))
    try:
        first_graph = build_interrupt_probe(first_checkpointer)
        interrupted = first_graph.invoke({"value": "before"}, config)
        assert "__interrupt__" in interrupted
    finally:
        close_checkpointer(first_checkpointer)

    second_checkpointer = create_checkpointer(str(database_path))
    try:
        resumed_graph = build_interrupt_probe(second_checkpointer)
        completed = resumed_graph.invoke(Command(resume="继续"), config)
        assert completed["answer"] == "继续"
        assert resumed_graph.get_state(config).values["answer"] == "继续"
    finally:
        close_checkpointer(second_checkpointer)
