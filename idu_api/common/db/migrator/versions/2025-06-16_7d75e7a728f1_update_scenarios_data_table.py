# pylint: disable=no-member,invalid-name,missing-function-docstring,too-many-statements
"""update scenarios data table

Revision ID: 7d75e7a728f1
Revises: 676ef0e8411b
Create Date: 2025-06-16 14:21:49.576063

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from idu_api.common.db.entities import scenarios_data

# revision identifiers, used by Alembic.
revision: str = "7d75e7a728f1"
down_revision: Union[str, None] = "676ef0e8411b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # drop columns phase, phase_percentage
    op.drop_column("scenarios_data", "phase", schema="user_projects")
    op.drop_column("scenarios_data", "phase_percentage", schema="user_projects")


def downgrade() -> None:

    scenario_phase_enum = sa.Enum(
        "investment",
        "pre_design",
        "design",
        "construction",
        "operation",
        "decommission",
        name="scenario_phase",
        schema="user_projects",
    )

    # revert dropping phase, phase_percentage
    op.add_column(
        "scenarios_data",
        sa.Column(
            "phase",
            scenario_phase_enum,
            nullable=True
        ),
        schema="user_projects"
    )

    op.add_column(
        "scenarios_data",
        sa.Column(
            "phase_percentage",
            sa.Float(3),
            nullable=True
        ),
        schema="user_projects"
    )
