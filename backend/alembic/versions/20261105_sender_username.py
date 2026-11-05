"""Preserve the sender's Telegram username at submission time."""
from alembic import op
import sqlalchemy as sa

revision = '20261105_sender_username'
down_revision = '20261105_telegram'
branch_labels = depends_on = None


def upgrade():
    op.add_column('applicants', sa.Column('telegram_username', sa.String(32)))


def downgrade():
    with op.batch_alter_table('applicants') as batch:
        batch.drop_column('telegram_username')
