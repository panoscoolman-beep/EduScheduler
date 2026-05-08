"""solution_status_error

Add 'error' to the allowed values of timetable_solutions.status so the
boot-time recovery hook can flip stuck 'generating' rows (left over
from a container restart mid-solve) to a clear error state.

Revision ID: c5d6e7f8a9b0
Revises: a1b2c3d4e5f6
Create Date: 2026-05-09 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op


revision: str = "c5d6e7f8a9b0"
down_revision: Union[str, None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_constraint("ck_solution_status", "timetable_solutions", type_="check")
    op.create_check_constraint(
        "ck_solution_status",
        "timetable_solutions",
        "status IN ('draft', 'generating', 'optimal', 'feasible', 'infeasible', 'error')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_solution_status", "timetable_solutions", type_="check")
    op.create_check_constraint(
        "ck_solution_status",
        "timetable_solutions",
        "status IN ('draft', 'generating', 'optimal', 'feasible', 'infeasible')",
    )
