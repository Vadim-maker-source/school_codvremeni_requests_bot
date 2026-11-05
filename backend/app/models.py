from datetime import datetime, timezone
from sqlalchemy import String, Text, ForeignKey, DateTime, JSON, UniqueConstraint, CheckConstraint, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base


def now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Staff(Base):
    __tablename__ = 'staff'
    __table_args__ = (CheckConstraint("role IN ('admin','operator')", name='role'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    login: Mapped[str] = mapped_column(String(64), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(20), default='operator')
    active: Mapped[bool] = mapped_column(default=True)
    telegram_id: Mapped[str | None] = mapped_column(String(32), unique=True)
    telegram_link_hash: Mapped[str | None] = mapped_column(String(64), unique=True)
    telegram_link_expires: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class ServerSession(Base):
    __tablename__ = 'sessions'
    id: Mapped[int] = mapped_column(primary_key=True)
    staff_id: Mapped[int] = mapped_column(ForeignKey('staff.id'), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    csrf_hash: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    revoked: Mapped[bool] = mapped_column(default=False)


class CategoryGroup(Base):
    __tablename__ = 'category_groups'
    id: Mapped[int] = mapped_column(primary_key=True)
    seed_key: Mapped[str | None] = mapped_column(String(50), unique=True)
    name: Mapped[str] = mapped_column(String(120))
    active: Mapped[bool] = mapped_column(default=True)
    sort_order: Mapped[int] = mapped_column(default=0)
    items: Mapped[list['CategoryItem']] = relationship(order_by='CategoryItem.sort_order, CategoryItem.id', lazy='selectin')


class CategoryItem(Base):
    __tablename__ = 'category_items'
    id: Mapped[int] = mapped_column(primary_key=True)
    seed_key: Mapped[str | None] = mapped_column(String(50), unique=True)
    group_id: Mapped[int] = mapped_column(ForeignKey('category_groups.id'), index=True)
    name: Mapped[str] = mapped_column(String(120))
    active: Mapped[bool] = mapped_column(default=True)
    sort_order: Mapped[int] = mapped_column(default=0)


class Applicant(Base):
    __tablename__ = 'applicants'
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    contact: Mapped[str] = mapped_column(String(255))
    telegram_user_id: Mapped[str | None] = mapped_column(String(32), index=True)
    telegram_username: Mapped[str | None] = mapped_column(String(32))
    telegram_chat_id: Mapped[str | None] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class Ticket(Base):
    __tablename__ = 'tickets'
    __table_args__ = (
        CheckConstraint("status IN ('new','in_progress','completed','rejected')", name='status'),
        CheckConstraint("source IN ('web','telegram')", name='source'),
        CheckConstraint("status NOT IN ('completed','rejected') OR (result IS NOT NULL AND length(trim(result)) > 0 AND closed_at IS NOT NULL)", name='closed_result'),
        {'sqlite_autoincrement': True},
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    number: Mapped[str | None] = mapped_column(String(40), unique=True, index=True)
    source: Mapped[str] = mapped_column(String(16), default='web')
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    applicant_id: Mapped[int] = mapped_column(ForeignKey('applicants.id'), index=True)
    applicant_name: Mapped[str] = mapped_column(String(120))
    contact_snapshot: Mapped[str] = mapped_column(String(255))
    group_id: Mapped[int] = mapped_column(ForeignKey('category_groups.id'), index=True)
    item_id: Mapped[int] = mapped_column(ForeignKey('category_items.id'), index=True)
    description: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default='new', index=True)
    assignee_id: Mapped[int | None] = mapped_column(ForeignKey('staff.id'), index=True)
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey('staff.id'))
    result: Mapped[str | None] = mapped_column(Text)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime)
    version: Mapped[int] = mapped_column(default=1)
    __mapper_args__ = {'version_id_col': version}
    group: Mapped[CategoryGroup] = relationship(lazy='joined')
    item: Mapped[CategoryItem] = relationship(lazy='joined')
    assignee: Mapped[Staff | None] = relationship(foreign_keys=[assignee_id], lazy='joined')


class History(Base):
    __tablename__ = 'history'
    id: Mapped[int] = mapped_column(primary_key=True)
    ticket_id: Mapped[int] = mapped_column(ForeignKey('tickets.id'), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    actor_id: Mapped[int | None] = mapped_column(ForeignKey('staff.id'))
    actor_type: Mapped[str] = mapped_column(String(20), default='staff')
    action: Mapped[str] = mapped_column(String(40))
    old_values: Mapped[dict] = mapped_column(JSON, default=dict)
    new_values: Mapped[dict] = mapped_column(JSON, default=dict)
    comment: Mapped[str | None] = mapped_column(Text)
    actor: Mapped[Staff | None] = relationship(lazy='joined')


class Notification(Base):
    __tablename__ = 'notifications'
    __table_args__ = (Index('ix_notifications_pending', 'state', 'next_attempt_at'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    ticket_id: Mapped[int] = mapped_column(ForeignKey('tickets.id'))
    history_id: Mapped[int] = mapped_column(ForeignKey('history.id'))
    event_key: Mapped[str] = mapped_column(String(120), unique=True)
    channel: Mapped[str] = mapped_column(String(20), default='telegram')
    recipient: Mapped[str] = mapped_column(String(32))
    payload: Mapped[dict] = mapped_column(JSON)
    state: Mapped[str] = mapped_column(String(20), default='pending')
    attempts: Mapped[int] = mapped_column(default=0)
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    last_error: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime)


class SystemState(Base):
    __tablename__ = 'system_state'
    key: Mapped[str] = mapped_column(String(50), primary_key=True)
    value: Mapped[int] = mapped_column(default=0)


class LoginAttempt(Base):
    __tablename__ = 'login_attempts'
    id: Mapped[int] = mapped_column(primary_key=True)
    bucket: Mapped[str] = mapped_column(String(64), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, index=True)


class TelegramDialog(Base):
    __tablename__ = 'telegram_dialogs'
    user_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    step: Mapped[str] = mapped_column(String(20), default='menu')
    data: Mapped[dict] = mapped_column(JSON, default=dict)


class TelegramSubmission(Base):
    __tablename__ = 'telegram_submissions'
    token: Mapped[str] = mapped_column(String(40), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(32))
    ticket_id: Mapped[int] = mapped_column(ForeignKey('tickets.id'))
