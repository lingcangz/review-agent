"""persist static-analysis metadata and verified finding attributes"""

import sqlalchemy as sa
from alembic import op

revision = "20260916_0005"
down_revision = "20260916_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "reviews",
        sa.Column("static_analysis", sa.JSON(), nullable=False, server_default="[]"),
    )
    op.add_column(
        "review_findings",
        sa.Column("confidence", sa.String(length=16), nullable=False, server_default="high"),
    )
    op.add_column(
        "review_findings",
        sa.Column("category", sa.String(length=16), nullable=False, server_default="correctness"),
    )


def downgrade() -> None:
    op.drop_column("review_findings", "category")
    op.drop_column("review_findings", "confidence")
    op.drop_column("reviews", "static_analysis")
