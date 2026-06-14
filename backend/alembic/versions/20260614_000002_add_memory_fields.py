"""Add recent_projects and frequent_assignees to long_term_memory.

Revision ID: 20260614_000002
Revises: 20260614_000001
Create Date: 2026-06-14
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20260614000002"
down_revision = "20260614000001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add recent_projects — JSON array of up to 5 project name strings
    op.add_column(
        "long_term_memory",
        sa.Column(
            "recent_projects",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    # Add frequent_assignees — JSON array of assignee name strings
    op.add_column(
        "long_term_memory",
        sa.Column(
            "frequent_assignees",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    # Drop the old session_summaries column — it was populated but never read back.
    # Data is not migrated; the column served no user-facing purpose.
    op.drop_column("long_term_memory", "session_summaries")


def downgrade() -> None:
    op.drop_column("long_term_memory", "frequent_assignees")
    op.drop_column("long_term_memory", "recent_projects")
    op.add_column(
        "long_term_memory",
        sa.Column(
            "session_summaries",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
