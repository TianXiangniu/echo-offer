from importlib import import_module


DOMAIN_ENTRYPOINTS = {
    "app.resume_intake": {
        "create_profile",
        "parse_and_store_resume",
        "analyze_resume_project",
        "stream_resume_project_analysis",
    },
    "app.interview_flow": {
        "create_session",
        "get_session_view",
        "submit_answer",
    },
    "app.assessment_flow": {
        "assess_session",
    },
    "app.reporting_flow": {
        "get_report",
        "list_interview_history",
        "get_profile_summary",
        "get_profile_history",
        "get_operation_job",
        "update_recommendation_status",
    },
}


def test_domain_entrypoints_live_in_their_domain_modules():
    for module_name, entrypoints in DOMAIN_ENTRYPOINTS.items():
        module = import_module(module_name)
        for entrypoint in entrypoints:
            function = getattr(module, entrypoint)
            assert function.__module__ == module_name
