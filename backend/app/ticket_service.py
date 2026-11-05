from fastapi import HTTPException
from sqlalchemy.orm import Session
from app.models import Applicant, CategoryGroup, CategoryItem, Staff, Ticket, History, now
from app.schemas import TicketCreate, TicketAction
from app.notifications import enqueue


def create_ticket(db: Session, data: TicketCreate, actor: Staff | None, *, source='web', telegram_user_id=None, telegram_chat_id=None, telegram_username=None):
    """Shared trusted entry point for web and the authenticated Telegram adapter.

    Caller owns commit/rollback; no Telegram identity is accepted by the public web API.
    """
    group, item = db.get(CategoryGroup, data.group_id), db.get(CategoryItem, data.item_id)
    if not group or not item or item.group_id != data.group_id:
        raise HTTPException(422, 'Элемент не принадлежит выбранной группе')
    if not group.active or not item.active:
        raise HTTPException(422, 'Эта категория отключена. Выберите другую')
    if source not in ('web', 'telegram'):
        raise ValueError('Unsupported source')
    applicant = Applicant(name=data.applicant_name, contact=data.contact, telegram_user_id=telegram_user_id,
                          telegram_chat_id=telegram_chat_id, telegram_username=telegram_username)
    db.add(applicant)
    db.flush()
    ticket = Ticket(applicant_id=applicant.id, applicant_name=data.applicant_name, contact_snapshot=data.contact,
                    group_id=data.group_id, item_id=data.item_id, description=data.description, source=source,
                    created_by_id=actor.id if actor else None)
    db.add(ticket)
    db.flush()
    # Database-generated primary key is atomic in SQLite and PostgreSQL; never MAX(id)+1.
    ticket.number = f'З-{ticket.created_at.year}-{ticket.id:06d}'
    db.flush()
    event = History(ticket_id=ticket.id, actor_id=actor.id if actor else None, actor_type='staff' if actor else 'telegram',
                    action='create', old_values={}, new_values={'status': 'new', 'source': source})
    db.add(event)
    db.flush()
    enqueue(db, ticket, event)
    return ticket


def apply_action(db: Session, ticket: Ticket, data: TicketAction, actor: Staff):
    if ticket.version != data.version:
        raise HTTPException(409, 'Заявка уже изменена другим сотрудником. Данные обновлены; повторите действие')
    if ticket.status in ('completed', 'rejected'):
        raise HTTPException(409, 'Закрытая заявка доступна только для просмотра')
    old = {'status': ticket.status, 'assignee_id': ticket.assignee_id,
           'assignee_name': ticket.assignee.name if ticket.assignee else None}
    if data.action == 'take':
        if ticket.status != 'new':
            raise HTTPException(409, 'Заявка уже взята в работу')
        ticket.status, ticket.assignee_id = 'in_progress', actor.id
    elif data.action == 'assign':
        target = db.get(Staff, data.assignee_id)
        if not target or not target.active:
            raise HTTPException(422, 'Исполнитель должен быть активным сотрудником')
        if actor.role == 'operator' and (target.role != 'operator' or target.id == actor.id):
            raise HTTPException(403, 'Оператор может назначить заявку только другому оператору')
        if ticket.assignee_id == target.id:
            return ticket
        ticket.assignee_id = target.id
    else:
        if ticket.status != 'in_progress':
            raise HTTPException(409, 'Сначала возьмите заявку в работу')
        ticket.status = 'completed' if data.action == 'complete' else 'rejected'
        ticket.result, ticket.closed_at = data.comment, now()
    ticket.updated_at = now()
    db.flush()  # SQLAlchemy adds WHERE version = previous_version; a lost race raises StaleDataError.
    target = db.get(Staff, ticket.assignee_id) if ticket.assignee_id else None
    event = History(ticket_id=ticket.id, actor_id=actor.id, action=data.action, old_values=old,
                    new_values={'status': ticket.status, 'assignee_id': ticket.assignee_id,
                                'assignee_name': target.name if target else None}, comment=data.comment)
    db.add(event)
    db.flush()
    enqueue(db, ticket, event)
    return ticket
