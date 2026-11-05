"""Telegram bindings and persistent conversations."""
from alembic import op
import sqlalchemy as sa

revision = '20261105_telegram'
down_revision = '50501bcf3682'
branch_labels = depends_on = None


def upgrade():
    with op.batch_alter_table('staff') as batch:
        batch.add_column(sa.Column('telegram_id', sa.String(32)))
        batch.add_column(sa.Column('telegram_link_hash', sa.String(64)))
        batch.add_column(sa.Column('telegram_link_expires', sa.DateTime()))
        batch.create_unique_constraint('uq_staff_telegram_id', ['telegram_id'])
        batch.create_unique_constraint('uq_staff_telegram_link_hash', ['telegram_link_hash'])
    op.create_table('telegram_dialogs',
        sa.Column('user_id', sa.String(32), primary_key=True),
        sa.Column('step', sa.String(20), nullable=False),
        sa.Column('data', sa.JSON(), nullable=False))
    op.create_table('telegram_submissions',
        sa.Column('token', sa.String(40), primary_key=True),
        sa.Column('user_id', sa.String(32), nullable=False),
        sa.Column('ticket_id', sa.Integer(), sa.ForeignKey('tickets.id'), nullable=False))


def downgrade():
    op.drop_table('telegram_submissions')
    op.drop_table('telegram_dialogs')
    with op.batch_alter_table('staff') as batch:
        batch.drop_constraint('uq_staff_telegram_link_hash', type_='unique')
        batch.drop_constraint('uq_staff_telegram_id', type_='unique')
        for name in ('telegram_link_expires', 'telegram_link_hash', 'telegram_id'):
            batch.drop_column(name)
