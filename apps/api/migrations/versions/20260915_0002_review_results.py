"""persist structured review results and bounded context requests"""

import sqlalchemy as sa
from alembic import op

revision = "20260915_0002"
down_revision = "20260915_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "reviews",
        sa.Column("requested_context_paths", sa.JSON(), nullable=False, server_default="[]"),
    )
    op.create_table(
        "review_findings",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "organization_id",
            sa.String(length=36),
            sa.ForeignKey("organizations.id"),
            nullable=False,
        ),
        sa.Column("review_id", sa.String(length=36), sa.ForeignKey("reviews.id"), nullable=False),
        sa.Column("severity", sa.String(length=2), nullable=False),
        sa.Column("path", sa.String(length=500), nullable=False),
        sa.Column("start_line", sa.Integer(), nullable=False),
        sa.Column("end_line", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=240), nullable=False),
        sa.Column("evidence", sa.Text(), nullable=False),
        sa.Column("recommendation", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_review_findings_organization_id", "review_findings", ["organization_id"])
    op.create_index("ix_review_findings_review_id", "review_findings", ["review_id"])


def downgrade() -> None:
    op.drop_table("review_findings")
    op.drop_column("reviews", "requested_context_paths")
