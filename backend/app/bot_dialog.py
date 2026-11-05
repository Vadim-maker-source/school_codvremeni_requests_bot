"""Persistent dialog; all database work runs outside the aiogram event loop."""
import secrets
from sqlalchemy import select
from fastapi import HTTPException
from app.models import Applicant, CategoryGroup, CategoryItem, Staff, Ticket, TelegramDialog, TelegramSubmission
from app.schemas import TicketCreate
from app.ticket_service import create_ticket
from app.telegram_link import bind

STATUSES = {'new': 'Новая', 'in_progress': 'В работе', 'completed': 'Выполнена', 'rejected': 'Отклонена'}
MENU = [('Создать заявку', 'new'), ('Мои заявки', 'mine'), ('Проверить статус', 'status'), ('Мои задания', 'assigned')]


def ticket_text(ticket):
    result = f'{ticket.number} · {STATUSES[ticket.status]}\n{ticket.description[:1200]}'
    return result + (f'\nРезультат: {ticket.result[:2000]}' if ticket.result else '')


def respond(db, user_id, name, text='', callback='', username=None):
    user_id = str(user_id)
    text = text.strip()
    dialog = db.get(TelegramDialog, user_id, with_for_update=True)
    if not dialog:
        dialog = TelegramDialog(user_id=user_id, step='menu', data={})
        db.add(dialog)
        db.flush()
    data = dict(dialog.data)
    telegram_contact = '@' + username if username else f'Telegram ID: {user_id}'
    if dialog.step in ('contact', 'confirm'):
        dialog.step = 'confirm'
        data['contact'] = telegram_contact
    command = text.split('@')[0] if text.startswith('/') else ''
    action = callback or {'/new': 'new', '/mine': 'mine', '/status': 'status', '/assigned': 'assigned',
                          '/cancel': 'cancel', '/start': 'menu'}.get(command, '')
    if text.startswith('/start link_'):
        return bind(db, text.split('link_', 1)[1], user_id), MENU
    if text == '/id':
        return f'Ваш Telegram ID: {user_id}. Для привязки используйте кнопку Telegram в кабинете.', MENU
    if callback.count(':') == 2:
        nonce, action, value = callback.split(':')
        saved = db.get(TelegramSubmission, nonce) if action == 'confirm' else None
        if saved and saved.user_id == user_id:
            return f'Заявка уже принята: {db.get(Ticket, saved.ticket_id).number}', MENU
        if nonce != data.get('nonce'):
            return 'Эта кнопка устарела. Продолжите последний диалог или нажмите /new.', []
    else:
        value = ''
    if action in ('menu', 'cancel'):
        dialog.step, dialog.data = 'menu', {}
        return 'Заявка · школьная служба. Выберите действие.', MENU
    if action == 'new':
        dialog.step, data = 'group', {'nonce': secrets.token_urlsafe(12), 'applicant_name': name[:120] or 'Заявитель'}
    elif action in ('mine', 'assigned'):
        if action == 'mine':
            query = select(Ticket).join(Applicant).where(Applicant.telegram_user_id == user_id)
        else:
            employee = db.scalar(select(Staff).where(Staff.telegram_id == user_id, Staff.active.is_(True)))
            if not employee:
                return 'Подключите Telegram через свой рабочий кабинет.', MENU
            query = select(Ticket).where(Ticket.assignee_id == employee.id, Ticket.status.in_(('new', 'in_progress')))
        rows = db.scalars(query.order_by(Ticket.id.desc()).limit(10)).all()
        dialog.step, dialog.data = 'menu', {}
        return '\n\n'.join(f'{t.number} · {STATUSES[t.status]}\n{t.description[:170]}' for t in rows) or 'Заявок пока нет.', MENU
    elif action == 'status':
        dialog.step, dialog.data = 'status', {}
        return 'Введите полный номер заявки, например З-2026-000001.', [('Отмена', 'cancel')]
    elif action == 'back':
        steps = ['menu', 'group', 'item', 'description', 'confirm']
        dialog.step = steps[max(0, steps.index(dialog.step) - 1)] if dialog.step in steps else 'menu'
    elif action == 'group' and dialog.step == 'group' and value.isdigit():
        group = db.get(CategoryGroup, int(value))
        if not group or not group.active:
            return 'Группа недоступна. Начните заново: /new.', MENU
        data['group_id'], dialog.step = group.id, 'item'
        data.pop('item_id', None)
    elif action == 'item' and dialog.step == 'item' and value.isdigit():
        item = db.get(CategoryItem, int(value))
        if not item or not item.active or item.group_id != data.get('group_id'):
            return 'Элемент недоступен. Начните заново: /new.', MENU
        data['item_id'], dialog.step = item.id, 'description'
    elif action == 'confirm' and dialog.step == 'confirm':
        try:
            ticket = create_ticket(db, TicketCreate(**{k: v for k, v in data.items() if k != 'nonce'}),
                None, source='telegram', telegram_user_id=user_id, telegram_chat_id=user_id, telegram_username=username)
        except HTTPException as error:
            dialog.step, dialog.data = 'menu', {}
            return f'{error.detail}. Начните заново: /new.', MENU
        db.add(TelegramSubmission(token=data['nonce'], user_id=user_id, ticket_id=ticket.id))
        dialog.step, dialog.data = 'menu', {}
        return f'Заявка {ticket.number} принята.\nИзменения статуса придут сюда.', MENU
    elif callback:
        return 'Продолжите последний шаг или нажмите /new.', []
    elif dialog.step == 'status':
        ticket = db.scalar(select(Ticket).join(Applicant).where(Ticket.number == text.upper(), Applicant.telegram_user_id == user_id))
        return (ticket_text(ticket) if ticket else 'Среди ваших заявок такой номер не найден.'), [('В меню', 'cancel')]
    elif dialog.step == 'description':
        if not text or len(text) > 5000 or text.startswith('/'):
            return 'Введите описание от 1 до 5000 символов.', [('Назад', f"{data['nonce']}:back:0"), ('Отмена', 'cancel')]
        data.update(description=text, contact=telegram_contact)
        dialog.step = 'confirm'
    dialog.data = data
    nonce = data.get('nonce', '')
    back = [('Назад', f'{nonce}:back:0'), ('Отмена', 'cancel')]
    if dialog.step == 'group':
        groups = db.scalars(select(CategoryGroup).where(CategoryGroup.active.is_(True)).order_by(CategoryGroup.sort_order, CategoryGroup.id)).all()
        return 'Выберите группу обращения.', [(g.name, f'{nonce}:group:{g.id}') for g in groups] + back
    if dialog.step == 'item':
        items = db.scalars(select(CategoryItem).where(CategoryItem.group_id == data['group_id'], CategoryItem.active.is_(True)).order_by(CategoryItem.sort_order, CategoryItem.id)).all()
        return 'Выберите тему обращения.', [(i.name, f'{nonce}:item:{i.id}') for i in items] + back
    if dialog.step == 'description':
        return 'Опишите проблему и место, где нужна помощь.', back
    if dialog.step == 'confirm':
        group, item = db.get(CategoryGroup, data['group_id']), db.get(CategoryItem, data['item_id'])
        return (f"Проверьте заявку\n{group.name} / {item.name}\n{data['description'][:3000]}\n"
                f"Контакт: {data['contact']}\nЗаявитель: {data['applicant_name']}"), [('Отправить заявку', f'{nonce}:confirm:0')] + back
    return 'Выберите действие или нажмите /new.', MENU
