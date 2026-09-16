"""persist bounded context ranges and remote review history metadata"""

import json

import sqlalchemy as sa
from alembic import op

revision = "20260916_0004"
down_revision = "20260915_0003"
branch_labels = None
depends_on = None


def _replace_context_table(include_ranges: bool) -> None:
    if include_ranges:
        op.create_table(
            "review_contexts_replacement",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column(
                "organization_id",
                sa.String(length=36),
                sa.ForeignKey("organizations.id"),
                nullable=False,
            ),
            sa.Column(
                "review_id", sa.String(length=36), sa.ForeignKey("reviews.id"), nullable=False
            ),
            sa.Column("path", sa.String(length=500), nullable=False),
            sa.Column("start_line", sa.Integer(), nullable=False),
            sa.Column("end_line", sa.Integer(), nullable=False),
            sa.Column("content", sa.Text(), nullable=False),
            sa.Column("raw_content_expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint(
                "review_id", "path", "start_line", "end_line", name="uq_review_context_range"
            ),
        )
        op.execute(
            "INSERT INTO review_contexts_replacement "
            "(id, organization_id, review_id, path, start_line, end_line, content, "
            "raw_content_expires_at, created_at) "
            "SELECT id, organization_id, review_id, path, 1, 100000, content, "
            "raw_content_expires_at, created_at FROM review_contexts"
        )
    else:
        op.create_table(
            "review_contexts_replacement",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column(
                "organization_id",
                sa.String(length=36),
                sa.ForeignKey("organizations.id"),
                nullable=False,
            ),
            sa.Column(
                "review_id", sa.String(length=36), sa.ForeignKey("reviews.id"), nullable=False
            ),
            sa.Column("path", sa.String(length=500), nullable=False),
            sa.Column("content", sa.Text(), nullable=False),
            sa.Column("raw_content_expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint("review_id", "path"),
        )
        op.execute(
            "INSERT INTO review_contexts_replacement "
            "(id, organization_id, review_id, path, content, raw_content_expires_at, created_at) "
            "SELECT context.id, context.organization_id, context.review_id, context.path, "
            "context.content, context.raw_content_expires_at, context.created_at "
            "FROM review_contexts AS context "
            "JOIN (SELECT review_id, path, MIN(id) AS id FROM review_contexts "
            "GROUP BY review_id, path) AS first_context ON context.id = first_context.id"
        )
    op.drop_table("review_contexts")
    op.rename_table("review_contexts_replacement", "review_contexts")


def upgrade() -> None:
    op.add_column(
        "reviews",
        sa.Column("requested_context", sa.JSON(), nullable=False, server_default="[]"),
    )
    bind = op.get_bind()
    reviews = sa.table(
        "reviews",
        sa.column("id", sa.String()),
        sa.column("requested_context_paths", sa.JSON()),
        sa.column("requested_context", sa.JSON()),
    )
    rows = bind.execute(sa.select(reviews.c.id, reviews.c.requested_context_paths)).mappings()
    for row in rows:
        paths = row["requested_context_paths"]
        if isinstance(paths, str):
            paths = json.loads(paths)
        requested_context = [
            {"path": path, "start_line": 1, "end_line": 500}
            for path in paths or []
            if isinstance(path, str)
        ]
        bind.execute(
            sa.update(reviews)
            .where(reviews.c.id == row["id"])
            .values(requested_context=requested_context)
        )
    op.drop_column("reviews", "requested_context_paths")
    _replace_context_table(include_ranges=True)


def downgrade() -> None:
    op.add_column(
        "reviews",
        sa.Column("requested_context_paths", sa.JSON(), nullable=False, server_default="[]"),
    )
    bind = op.get_bind()
    reviews = sa.table(
        "reviews",
        sa.column("id", sa.String()),
        sa.column("requested_context", sa.JSON()),
        sa.column("requested_context_paths", sa.JSON()),
    )
    rows = bind.execute(sa.select(reviews.c.id, reviews.c.requested_context)).mappings()
    for row in rows:
        requested_context = row["requested_context"]
        if isinstance(requested_context, str):
            requested_context = json.loads(requested_context)
        paths = [item["path"] for item in requested_context or [] if isinstance(item, dict)]
        bind.execute(
            sa.update(reviews)
            .where(reviews.c.id == row["id"])
            .values(requested_context_paths=paths)
        )
    op.drop_column("reviews", "requested_context")
    _replace_context_table(include_ranges=False)
