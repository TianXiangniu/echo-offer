"""Replace the legacy user-wide skill uniqueness with profile scope.

Revision ID: 0003_profile_skill_state_scope
Revises: 0002_assessment_batches_and_profile_scope
"""
from alembic import op
from sqlalchemy import inspect


revision = "0003_profile_skill_state_scope"
down_revision = "0002_assessment_batches_and_profile_scope"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if not inspect(bind).has_table("candidate_knowledge_states"):
        return

    unique_constraints = {
        constraint["name"]
        for constraint in inspect(bind).get_unique_constraints(
            "candidate_knowledge_states"
        )
        if constraint.get("name")
    }
    legacy_name = "uq_candidate_skill_state"
    current_name = "uq_candidate_profile_skill_state"
    if legacy_name in unique_constraints and current_name not in unique_constraints:
        # SQLite cannot drop a table constraint in place. Alembic's batch mode
        # performs a copy-and-move while preserving all existing rows.
        with op.batch_alter_table(
            "candidate_knowledge_states", recreate="always"
        ) as batch_op:
            batch_op.drop_constraint(legacy_name, type_="unique")
            batch_op.create_unique_constraint(
                current_name, ["profile_id", "skill_id"]
            )


def downgrade() -> None:
    pass
