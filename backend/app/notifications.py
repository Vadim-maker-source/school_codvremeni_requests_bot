"""Notifications are queued in the same transaction as the ticket event."""
from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.dialects.postgresql import insert as pg_insert
from app.models import Applicant, Staff, Notification, now


def enqueue(db, ticket, event):
    insert = sqlite_insert if db.bind.dialect.name == 'sqlite' else pg_insert
    payload = {'number': ticket.number, 'status': ticket.status, 'result': ticket.result}
    recipients = []
    applicant = db.get(Applicant, ticket.applicant_id)
    if applicant.telegram_chat_id and event.action in ('take', 'complete', 'reject'):
        recipients.append((applicant.telegram_chat_id, f'telegram:history:{event.id}', payload))
    if event.action in ('create', 'take', 'complete', 'reject'):
        employees = db.scalars(select(Staff).where(Staff.active.is_(True), Staff.role == 'admin', Staff.telegram_id.is_not(None))).all()
    else:
        employees = []
    if event.action in ('assign', 'take') and ticket.assignee_id:
        employee = db.get(Staff, ticket.assignee_id)
        if employee.active and employee.telegram_id:
            employees.append(employee)
    assignee = db.get(Staff, ticket.assignee_id) if ticket.assignee_id else None
    for employee in {s.id: s for s in employees}.values():
        kind = f'admin_{event.action}' if employee.role == 'admin' and event.action in ('take', 'complete', 'reject') else event.action
        recipients.append((employee.telegram_id, f'telegram:history:{event.id}:staff:{employee.id}',
            payload | {'staff_id': employee.id, 'kind': kind, 'description': ticket.description[:800],
                       'applicant_copy': employee.telegram_id == applicant.telegram_chat_id and event.action in ('take', 'complete', 'reject'),
                       'assignee_name': assignee.name if assignee else 'Не назначен',
                       'applicant_name': ticket.applicant_name, 'telegram_user_id': applicant.telegram_user_id,
                       'telegram_username': applicant.telegram_username,
                       'category': f'{ticket.group.name} / {ticket.item.name}'}))
    # A person with two roles receives one richer message for this event.
    unique = {recipient: (key, data) for recipient, key, data in recipients}
    for recipient, (key, data) in unique.items():
        db.execute(insert(Notification).values(ticket_id=ticket.id, history_id=event.id, event_key=key,
            channel='telegram', recipient=recipient, payload=data, state='pending', attempts=0,
            next_attempt_at=now(), created_at=now()).on_conflict_do_nothing(index_elements=['event_key']))
