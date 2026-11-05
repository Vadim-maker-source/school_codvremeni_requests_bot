from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, func, update
from sqlalchemy.orm import Session
from app.auth import current_user, admin_user, hasher
from app.database import get_db
from app.models import Staff, ServerSession, SystemState
from app.schemas import StaffOut, StaffCreate, StaffEdit

router = APIRouter(prefix='/api/staff', tags=['Сотрудники'])


@router.get('', response_model=list[StaffOut])
def list_staff(user: Staff = Depends(current_user), db: Session = Depends(get_db)):
    query = select(Staff).order_by(Staff.name)
    if user.role != 'admin':
        query = query.where(Staff.active.is_(True))
    return db.scalars(query).all()


@router.post('', response_model=StaffOut, status_code=201)
def create(data: StaffCreate, user: Staff = Depends(admin_user), db: Session = Depends(get_db)):
    if db.scalar(select(Staff.id).where(Staff.login == data.login)):
        raise HTTPException(409, 'Этот логин уже используется')
    employee = Staff(name=data.name, login=data.login, role=data.role, password_hash=hasher.hash(data.password))
    db.add(employee)
    db.commit()
    return employee


@router.put('/{staff_id}', response_model=StaffOut)
def edit(staff_id: int, data: StaffEdit, user: Staff = Depends(admin_user), db: Session = Depends(get_db)):
    # Serialize administration in both SQLite and PostgreSQL to protect the last admin across concurrent requests.
    db.execute(update(SystemState).where(SystemState.key == 'staff_guard').values(value=SystemState.value + 1))
    db.expire_all()
    employee = db.get(Staff, staff_id)
    if not employee:
        raise HTTPException(404, 'Сотрудник не найден')
    if employee.role == 'admin' and employee.active and (not data.active or data.role != 'admin'):
        count = db.scalar(select(func.count()).select_from(Staff).where(Staff.role == 'admin', Staff.active.is_(True)))
        if count <= 1:
            raise HTTPException(409, 'Нельзя отключить или понизить последнего активного администратора')
    revoke = bool(data.password) or not data.active or employee.role != data.role
    employee.name, employee.role, employee.active = data.name, data.role, data.active
    if data.password:
        employee.password_hash = hasher.hash(data.password)
    if revoke:
        employee.telegram_link_hash = employee.telegram_link_expires = None
        db.execute(update(ServerSession).where(ServerSession.staff_id == employee.id).values(revoked=True))
    db.commit()
    return employee
