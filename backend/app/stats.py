from fastapi import APIRouter, Depends
from sqlalchemy import select, func
from sqlalchemy.orm import Session
from app.auth import current_user, admin_user
from app.database import get_db
from app.models import Staff, Ticket, CategoryGroup, CategoryItem
from app.schemas import StatsOut

router = APIRouter(prefix='/api/stats', tags=['Статистика'])


def counts(db):
    result = dict(db.execute(select(Ticket.status, func.count()).group_by(Ticket.status)).all())
    return {key: result.get(key, 0) for key in ('new', 'in_progress', 'completed', 'rejected')}


@router.get('/summary', response_model=StatsOut)
def summary(user: Staff = Depends(current_user), db: Session = Depends(get_db)):
    statuses = counts(db)
    return {'total': sum(statuses.values()), 'statuses': statuses}


@router.get('', response_model=StatsOut)
def full(user: Staff = Depends(admin_user), db: Session = Depends(get_db)):
    statuses = counts(db)
    def distribution(model, column):
        rows = db.execute(select(model.name, func.count(Ticket.id)).outerjoin(Ticket, column == model.id).group_by(model.id, model.name).order_by(model.name)).all()
        return [{'name': name, 'count': count} for name, count in rows]
    assignees = distribution(Staff, Ticket.assignee_id)
    assignees.append({'name': 'Без исполнителя', 'count': db.scalar(select(func.count()).select_from(Ticket).where(Ticket.assignee_id.is_(None)))})
    return {'total': sum(statuses.values()), 'statuses': statuses, 'groups': distribution(CategoryGroup, Ticket.group_id),
            'items': distribution(CategoryItem, Ticket.item_id), 'assignees': assignees}
