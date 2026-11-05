from datetime import date, datetime, time, timedelta
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func, or_
from sqlalchemy.orm import Session
from app.auth import current_user
from app.database import get_db
from app.models import Applicant, Staff, Ticket, History
from app.schemas import TicketCreate, TicketAction, TicketOut, TicketDetail, TicketPage
from app.ticket_service import create_ticket, apply_action

router = APIRouter(prefix='/api/tickets', tags=['Заявки'])


@router.get('', response_model=TicketPage)
def list_tickets(q: str = Query('', max_length=200), status: str | None = None, group_id: int | None = None,
                 assignee_id: int | None = None, date_from: date | None = None, date_to: date | None = None,
                 page: int = Query(1, ge=1), page_size: int = Query(15, ge=1, le=100),
                 user: Staff = Depends(current_user), db: Session = Depends(get_db)):
    criteria = []
    if status:
        if status not in ('new', 'in_progress', 'completed', 'rejected'):
            raise HTTPException(422, 'Неизвестный статус')
        criteria.append(Ticket.status == status)
    if group_id:
        criteria.append(Ticket.group_id == group_id)
    if assignee_id is not None:
        criteria.append(Ticket.assignee_id.is_(None) if assignee_id == 0 else Ticket.assignee_id == assignee_id)
    if date_from and date_to and date_from > date_to:
        raise HTTPException(422, 'Начальная дата должна быть раньше конечной')
    # User dates are Moscow local calendar dates; stored timestamps are UTC.
    if date_from:
        criteria.append(Ticket.created_at >= datetime.combine(date_from, time.min) - timedelta(hours=3))
    if date_to:
        criteria.append(Ticket.created_at < datetime.combine(date_to + timedelta(days=1), time.min) - timedelta(hours=3))
    if q.strip():
        escaped = q.strip().replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
        criteria.append(or_(Ticket.number.ilike(f'%{escaped}%', escape='\\'), Ticket.description.ilike(f'%{escaped}%', escape='\\')))
    total = db.scalar(select(func.count()).select_from(Ticket).where(*criteria))
    rows = db.scalars(select(Ticket).where(*criteria).order_by(Ticket.created_at.desc(), Ticket.id.desc()).offset((page - 1) * page_size).limit(page_size)).unique().all()
    return {'items': rows, 'total': total, 'page': page, 'page_size': page_size}


@router.post('', response_model=TicketOut, status_code=201)
def create(data: TicketCreate, user: Staff = Depends(current_user), db: Session = Depends(get_db)):
    ticket = create_ticket(db, data, user)
    db.commit()
    return db.get(Ticket, ticket.id)


def get_ticket(db, ticket_id):
    ticket = db.get(Ticket, ticket_id)
    if not ticket:
        raise HTTPException(404, 'Заявка не найдена')
    return ticket


@router.get('/{ticket_id}', response_model=TicketDetail)
def detail(ticket_id: int, user: Staff = Depends(current_user), db: Session = Depends(get_db)):
    ticket = get_ticket(db, ticket_id)
    result = TicketOut.model_validate(ticket).model_dump()
    applicant = db.get(Applicant, ticket.applicant_id)
    result.update(telegram_user_id=applicant.telegram_user_id, telegram_username=applicant.telegram_username)
    result['history'] = db.scalars(select(History).where(History.ticket_id == ticket_id).order_by(History.id)).all()
    return result


@router.post('/{ticket_id}/actions', response_model=TicketOut)
def action(ticket_id: int, data: TicketAction, user: Staff = Depends(current_user), db: Session = Depends(get_db)):
    ticket = apply_action(db, get_ticket(db, ticket_id), data, user)
    db.commit()
    db.expire_all()
    return db.get(Ticket, ticket.id)
