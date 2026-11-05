from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.auth import current_user, admin_user
from app.database import get_db
from app.models import Staff, CategoryGroup, CategoryItem
from app.schemas import GroupOut, ItemOut, ItemInput

router = APIRouter(prefix='/api/categories', tags=['Классификаторы'])


@router.get('', response_model=list[GroupOut])
def categories(user: Staff = Depends(current_user), db: Session = Depends(get_db)):
    return db.scalars(select(CategoryGroup).order_by(CategoryGroup.sort_order, CategoryGroup.id)).all()


@router.post('/groups', response_model=GroupOut, status_code=201)
def create_group(data: ItemInput, user: Staff = Depends(admin_user), db: Session = Depends(get_db)):
    group = CategoryGroup(**data.model_dump())
    db.add(group)
    db.commit()
    return group


@router.put('/groups/{group_id}', response_model=GroupOut)
def edit_group(group_id: int, data: ItemInput, user: Staff = Depends(admin_user), db: Session = Depends(get_db)):
    group = db.get(CategoryGroup, group_id)
    if not group:
        raise HTTPException(404, 'Группа не найдена')
    for key, value in data.model_dump().items():
        setattr(group, key, value)
    db.commit()
    return group


@router.post('/groups/{group_id}/items', response_model=ItemOut, status_code=201)
def create_item(group_id: int, data: ItemInput, user: Staff = Depends(admin_user), db: Session = Depends(get_db)):
    if not db.get(CategoryGroup, group_id):
        raise HTTPException(404, 'Группа не найдена')
    item = CategoryItem(group_id=group_id, **data.model_dump())
    db.add(item)
    db.commit()
    return item


@router.put('/items/{item_id}', response_model=ItemOut)
def edit_item(item_id: int, data: ItemInput, user: Staff = Depends(admin_user), db: Session = Depends(get_db)):
    item = db.get(CategoryItem, item_id)
    if not item:
        raise HTTPException(404, 'Элемент не найден')
    for key, value in data.model_dump().items():
        setattr(item, key, value)
    db.commit()
    return item
