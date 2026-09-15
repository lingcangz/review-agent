"""bind email login tokens to their requested organization"""

import sqlalchemy as sa
from alembic import op

revision = "20260915_0003"
down_revision = "20260915_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("email_login_tokens") as batch:
        batch.add_column(
            sa.Column(
                "organization_id",
                sa.String(length=36),
                sa.ForeignKey("organizations.id", name="fk_email_login_tokens_organization_id"),
                nullable=True,
            )
        )
        batch.create_index("ix_email_login_tokens_organization_id", ["organization_id"])


def downgrade() -> None:
    with op.batch_alter_table("email_login_tokens") as batch:
        batch.drop_index("ix_email_login_tokens_organization_id")
        batch.drop_constraint("fk_email_login_tokens_organization_id", type_="foreignkey")
        batch.drop_column("organization_id")
