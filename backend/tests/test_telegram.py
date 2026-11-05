"""Bot tests use only the temporary database and fake Telegram transports."""
import asyncio
from datetime import timedelta
import pytest
from sqlalchemy import select, func
from aiogram.exceptions import TelegramForbiddenError, TelegramRetryAfter
from aiogram.methods import SendMessage
from app import bot
from app.bot_dialog import respond
from app.models import Applicant, Staff, TelegramDialog, TelegramSubmission, Ticket, History, Notification, now
from app.telegram_link import bind
from app.config import settings
from app.schemas import TicketCreate, TicketAction
from app.ticket_service import create_ticket, apply_action

DATA = dict(applicant_name='Анна', contact='test@example.invalid', group_id=1, item_id=1, description='Не включается проектор')


def conversation(context, user=101):
    def call(text='', callback=''):
        with context['factory'].begin() as db:
            return respond(db, user, 'Анна Петрова', text, callback)
    return call


def confirmation(call):
    _, buttons = call('/new')
    _, buttons = call(callback=buttons[0][1])
    _, buttons = call(callback=buttons[0][1])
    answer, buttons = call('Не включается проектор')
    assert 'Проверьте заявку' in answer
    assert 'Telegram ID: 101' in answer
    return buttons[0][1]


def test_dialog_persistent_back_validation_owner_and_duplicate(context):
    call = conversation(context)
    call('/new')
    with context['factory']() as db:
        assert db.get(TelegramDialog, '101').step == 'group'
    token = confirmation(call)
    _, buttons = call(callback=token.split(':')[0] + ':back:0')
    assert '5000' in call('')[0]
    _, buttons = call('Не включается проектор')
    first = call(callback=buttons[0][1])[0]
    assert 'принята' in first
    assert 'уже принята' in call(callback=buttons[0][1])[0]
    with context['factory']() as db:
        assert db.scalar(select(func.count()).select_from(Ticket)) == 1
        assert db.scalar(select(func.count()).select_from(TelegramSubmission)) == 1
        ticket = db.scalar(select(Ticket))
        number = ticket.number
        assert ticket.source == 'telegram'
    call('/status')
    assert number in call(number)[0]
    other = conversation(context, 202)
    other('/status')
    assert 'не найден' in other(number)[0]
    other('/new')
    assert 'устарела' in other(callback=token)[0]
    assert 'Подключите' in other('/assigned')[0]


def test_dialog_cancel_stale_and_disabled_category(context):
    call=conversation(context)
    old=confirmation(call)
    call('/cancel')
    call('/new')
    assert 'устарела' in call(callback=old)[0]
    token=confirmation(call)
    with context['factory'].begin() as db:
        from app.models import CategoryItem
        db.get(CategoryItem,1).active=False
    assert 'отключена' in call(callback=token)[0]
    with context['factory']() as db:
        assert db.scalar(select(func.count()).select_from(Ticket))==0


def test_binding_auth_expiry_single_use_unique_unlink(context, monkeypatch):
    monkeypatch.setattr(settings,'telegram_bot_username','test_bot')
    monkeypatch.setattr(settings,'telegram_bot_token','test-only')
    a,c=context['client']('admin'),context['client']()
    assert context['anon'].post('/api/me/telegram').status_code==401
    assert c.post('/api/me/telegram',headers={'X-CSRF-Token':'bad'}).status_code==403
    link=c.post('/api/me/telegram').json()['url'].split('link_')[1]
    with context['factory'].begin() as db:
        assert 'подключён' in bind(db,link,'101')
    assert c.get('/api/me/telegram').json()['linked']
    with context['factory'].begin() as db:
        assert 'использована' in bind(db,link,'202')
    admin_link=a.post('/api/me/telegram').json()['url'].split('link_')[1]
    with context['factory'].begin() as db:
        assert 'другой' in bind(db,admin_link,'101')
    assert c.delete('/api/me/telegram').status_code==200
    with context['factory'].begin() as db:
        assert 'подключён' in bind(db,admin_link,'101')
    expired=c.post('/api/me/telegram').json()['url'].split('link_')[1]
    with context['factory'].begin() as db:
        db.get(Staff,2).telegram_link_expires=now()-timedelta(seconds=1)
    with context['factory'].begin() as db:
        assert 'истекла' in bind(db,expired,'202')
    assert 'telegram_id' not in a.get('/api/staff').json()[0]


def jobs(context):
    with context['factory']() as db:
        return db.scalars(select(Notification).order_by(Notification.id)).all()


def test_admin_assignee_applicant_notifications_and_revoked_binding(context, monkeypatch):
    monkeypatch.setattr(bot,'SessionLocal',context['factory'])
    with context['factory'].begin() as db:
        db.get(Staff,1).telegram_id='111'
        db.get(Staff,2).telegram_id='222'
        ticket=create_ticket(db,TicketCreate(**DATA),None,source='telegram',telegram_user_id='333',telegram_chat_id='333')
        apply_action(db,ticket,TicketAction(action='assign',version=ticket.version,assignee_id=2),db.get(Staff,1))
        apply_action(db,ticket,TicketAction(action='take',version=ticket.version),db.get(Staff,2))
        apply_action(db,ticket,TicketAction(action='complete',version=ticket.version,comment='Готово'),db.get(Staff,2))
    rows=jobs(context)
    assert [r.recipient for r in rows]==['111','222','333','111','222','333','111']
    with context['factory'].begin() as db:
        db.get(Staff,1).telegram_id=None
        db.get(Staff,2).active=False
    delivered=[]
    class Transport:
        async def send_message(self, recipient, text, **kwargs):
            delivered.append(recipient)
    while asyncio.run(bot.send_one(Transport())):
        pass
    assert delivered==['333','333']
    assert all(row.state==('sent' if row.recipient=='333' else 'cancelled') for row in jobs(context))



@pytest.mark.parametrize('error,expected',[(TelegramForbiddenError(method=SendMessage(chat_id=1,text='x'),message='blocked'),'failed'),
    (TelegramRetryAfter(method=SendMessage(chat_id=1,text='x'),message='retry',retry_after=5),'pending'),(TimeoutError(),'pending')])
def test_delivery_failure_retry_and_lease(context, monkeypatch, error, expected):
    monkeypatch.setattr(bot,'SessionLocal',context['factory'])
    with context['factory'].begin() as db:
        t=create_ticket(db,TicketCreate(**DATA),None,source='telegram',telegram_chat_id='333')
        apply_action(db,t,TicketAction(action='take',version=t.version),db.get(Staff,2))
    class Transport:
        async def send_message(self,*args,**kwargs):
            raise error
    assert asyncio.run(bot.send_one(Transport()))
    row=jobs(context)[0]
    assert row.state==expected and row.attempts==1 and row.last_error==type(error).__name__
    if expected=='pending':
        assert bot.claim() is None
        with context['factory'].begin() as db:
            n=db.get(Notification,row.id)
            n.next_attempt_at=now()-timedelta(seconds=1)
            n.state='sending'
        assert bot.claim()[0]==row.id
        assert bot.claim() is None

def test_aiogram_routes_without_contact_prompt(context, monkeypatch):
    from aiogram import Bot
    from aiogram.client.session.base import BaseSession
    from aiogram.methods import SendMessage, AnswerCallbackQuery
    from aiogram.types import Chat, Message
    monkeypatch.setattr(bot,'SessionLocal',context['factory'])
    answers=[]
    class Transport(BaseSession):
        async def close(self): pass
        async def stream_content(self,*args,**kwargs):
            yield b''
        async def make_request(self,client,method,timeout=None):
            if isinstance(method,SendMessage):
                answers.append(method)
                return Message(message_id=1,date=now(),chat=Chat(id=101,type='private'),text=method.text)
            if isinstance(method,AnswerCallbackQuery):
                return True
            raise AssertionError(type(method).__name__)
    async def run():
        async with Bot('123456:OFFLINE_ONLY_TEST_TOKEN',session=Transport()) as client:
            async def update(index,text=None,callback=None):
                message={'message_id':index,'date':int(now().timestamp()),'chat':{'id':101,'type':'private'},
                         'from':{'id':101,'is_bot':False,'first_name':'Анна','username':'anna_school'},'text':text}
                raw={'update_id':index,'message':message} if callback is None else {
                    'update_id':index,'callback_query':{'id':str(index),'from':message['from'],'chat_instance':'1',
                                                       'message':message,'data':callback}}
                await bot.dispatcher.feed_raw_update(client,raw)
            await update(1,'/new')
            group=answers[-1].reply_markup.inline_keyboard[0][0].callback_data
            await update(2,callback=group)
            item=answers[-1].reply_markup.inline_keyboard[0][0].callback_data
            await update(3,callback=item)
            await update(4,'Проверить проектор')
            assert 'Проверьте заявку' in answers[-1].text
            assert 'Контакт: @anna_school' in answers[-1].text
            assert all('Оставьте контакт' not in answer.text for answer in answers)
            token=answers[-1].reply_markup.inline_keyboard[0][0].callback_data
            await update(6,callback=token)
            assert 'принята' in answers[-1].text
            await update(7,callback=token)
            assert 'уже принята' in answers[-1].text
    asyncio.run(run())
    with context['factory']() as db:
        applicant=db.scalar(select(Applicant))
        assert applicant.telegram_user_id=='101'
        assert applicant.telegram_username=='anna_school'
        assert applicant.contact=='@anna_school'
        ticket=db.scalar(select(Ticket))
        ticket_id=ticket.id
    detail=context['client']('admin').get(f'/api/tickets/{ticket_id}').json()
    assert detail['telegram_username']=='anna_school' and detail['telegram_user_id']=='101'

@pytest.mark.parametrize('username',['anna_school',None])
def test_sender_identity_in_admin_notification(context,username):
    with context['factory'].begin() as db:
        db.get(Staff,1).telegram_id='111'
        ticket=create_ticket(db,TicketCreate(**DATA),None,source='telegram',
            telegram_user_id='101',telegram_chat_id='101',telegram_username=username)
        payload=db.scalar(select(Notification)).payload
        assert payload['telegram_user_id']=='101' and payload['telegram_username']==username
        text=bot.notification_text(payload)
        assert 'Telegram ID: 101' in text
        assert ('@anna_school' if username else 'не указан') in text

def test_resume_old_contact_step_without_requesting_contact(context):
    call=conversation(context)
    token=confirmation(call)
    with context['factory'].begin() as db:
        db.get(TelegramDialog,'101').step='contact'
    text,buttons=call('Продолжить')
    assert 'Проверьте заявку' in text and 'Контакт: Telegram ID: 101' in text
    assert buttons[0][1]==token
    assert 'принята' in call(callback=token)[0]

def test_applicant_notified_on_take_but_not_assignment(context,monkeypatch):
    monkeypatch.setattr(bot,'SessionLocal',context['factory'])
    with context['factory'].begin() as db:
        ticket=create_ticket(db,TicketCreate(**DATA),None,source='telegram',telegram_user_id='333',telegram_chat_id='333')
        apply_action(db,ticket,TicketAction(action='assign',version=ticket.version,assignee_id=2),db.get(Staff,1))
        number=ticket.number
        assert not db.scalars(select(Notification)).all()
        apply_action(db,ticket,TicketAction(action='take',version=ticket.version),db.get(Staff,2))
    sent=[]
    class Transport:
        async def send_message(self,recipient,text,**kwargs):
            sent.append((recipient,text))
    assert asyncio.run(bot.send_one(Transport()))
    assert sent==[('333',f'Заявка №{number} принята в работу.')]
    assert jobs(context)[0].state=='sent'
    assert not asyncio.run(bot.send_one(Transport()))

@pytest.mark.parametrize('terminal',['complete','reject'])
def test_admin_receives_lifecycle_without_duplicate_if_assignee(context,monkeypatch,terminal):
    monkeypatch.setattr(bot,'SessionLocal',context['factory'])
    with context['factory'].begin() as db:
        admin=db.get(Staff,1)
        admin.telegram_id='111'
        ticket=create_ticket(db,TicketCreate(**DATA),None,source='telegram',telegram_chat_id='333')
        apply_action(db,ticket,TicketAction(action='take',version=ticket.version),admin)
        apply_action(db,ticket,TicketAction(action=terminal,version=ticket.version,comment='Проверочный результат'),admin)
    rows=jobs(context)
    assert [r.payload.get('kind') for r in rows if r.recipient=='111']==['create','admin_take','admin_'+terminal]
    delivered=[]
    class Transport:
        async def send_message(self,recipient,text,**kwargs):
            delivered.append((recipient,text))
    while asyncio.run(bot.send_one(Transport())):
        pass
    admin_messages=[text for recipient,text in delivered if recipient=='111']
    assert len(admin_messages)==3
    assert 'Принята в работу' in admin_messages[1] and 'Исполнитель: Администратор' in admin_messages[1]
    assert ('Результат' if terminal=='complete' else 'Причина')+': Проверочный результат' in admin_messages[2]
    assert all(row.state=='sent' for row in jobs(context))

@pytest.mark.parametrize('source',['web','telegram'])
@pytest.mark.parametrize('terminal',['complete','reject'])
def test_recipient_matrix_multiple_roles(context,monkeypatch,source,terminal):
    monkeypatch.setattr(bot,'SessionLocal',context['factory'])
    with context['factory'].begin() as db:
        admin,operator=db.get(Staff,1),db.get(Staff,2)
        admin.telegram_id,operator.telegram_id='111','222'
        extra=[Staff(name=name,login=login,role=role,active=active,telegram_id=chat,password_hash=admin.password_hash)
               for name,login,role,active,chat in [
                ('Другой администратор','admin2','admin',True,'444'),
                ('Другой оператор','operator2','operator',True,'555'),
                ('Отключённый администратор','disabled','admin',False,'666'),
                ('Администратор без Telegram','unlinked','admin',True,None)]]
        db.add_all(extra)
        db.flush()
        colleague=extra[1].id
        ticket=create_ticket(db,TicketCreate(**DATA),admin if source=='web' else None,source=source,
            telegram_user_id='333' if source=='telegram' else None,telegram_chat_id='333' if source=='telegram' else None)
        ticket_id=ticket.id
    sent=[]
    class Transport:
        async def send_message(self,recipient,text,**kwargs):
            sent.append(recipient)
    def drain(expected):
        sent.clear()
        while asyncio.run(bot.send_one(Transport())):
            pass
        assert sorted(sent)==sorted(expected)
    def action(name,actor,**extra):
        with context['factory'].begin() as db:
            ticket=db.get(Ticket,ticket_id)
            apply_action(db,ticket,TicketAction(action=name,version=ticket.version,**extra),db.get(Staff,actor))
    drain(['111','444'])
    action('assign',1,assignee_id=2)
    drain(['222'])
    action('assign',2,assignee_id=colleague)
    drain(['555'])
    action('take',colleague)
    drain(['111','444','555']+(['333'] if source=='telegram' else []))
    action(terminal,colleague,comment='Проверочный результат')
    drain(['111','444']+(['333'] if source=='telegram' else []))
    assert all(row.state=='sent' for row in jobs(context))


def test_revoked_head_does_not_block_applicant_delivery(context,monkeypatch):
    monkeypatch.setattr(bot,'SessionLocal',context['factory'])
    with context['factory'].begin() as db:
        admin=db.get(Staff,1)
        admin.telegram_id='111'
        ticket=create_ticket(db,TicketCreate(**DATA),None,source='telegram',telegram_chat_id='333')
        apply_action(db,ticket,TicketAction(action='take',version=ticket.version),db.get(Staff,2))
        admin.telegram_id=None
    delivered=[]
    class Transport:
        async def send_message(self,recipient,text,**kwargs):
            delivered.append(recipient)
    assert asyncio.run(bot.send_one(Transport()))
    assert delivered==['333']


def test_applicant_also_admin_gets_one_message_per_event(context,monkeypatch):
    monkeypatch.setattr(bot,'SessionLocal',context['factory'])
    with context['factory'].begin() as db:
        admin=db.get(Staff,1)
        admin.telegram_id='111'
        ticket=create_ticket(db,TicketCreate(**DATA),None,source='telegram',telegram_chat_id='111',telegram_user_id='111')
        apply_action(db,ticket,TicketAction(action='take',version=ticket.version),db.get(Staff,2))
    rows=jobs(context)
    assert len({(row.history_id,row.recipient) for row in rows})==len(rows)

def test_dual_role_revocation_preserves_only_applicant_message(context,monkeypatch):
    monkeypatch.setattr(bot,'SessionLocal',context['factory'])
    with context['factory'].begin() as db:
        admin=db.get(Staff,1)
        admin.telegram_id='111'
        ticket=create_ticket(db,TicketCreate(**DATA),None,source='telegram',telegram_chat_id='111',telegram_user_id='111')
        apply_action(db,ticket,TicketAction(action='take',version=ticket.version),db.get(Staff,2))
        admin.telegram_id=None
    delivered=[]
    class Transport:
        async def send_message(self,recipient,text,**kwargs):
            delivered.append((recipient,text))
    while asyncio.run(bot.send_one(Transport())):
        pass
    assert len(delivered)==1 and delivered[0][0]=='111'
    assert 'принята в работу' in delivered[0][1] and 'Исполнитель:' not in delivered[0][1]

@pytest.mark.parametrize('change',['unlink','rebind','disable','demote'])
def test_admin_recipient_checked_again_before_delivery(context,monkeypatch,change):
    monkeypatch.setattr(bot,'SessionLocal',context['factory'])
    with context['factory'].begin() as db:
        admin=db.get(Staff,1)
        admin.telegram_id='111'
        create_ticket(db,TicketCreate(**DATA),None,source='telegram',telegram_chat_id='333')
    with context['factory'].begin() as db:
        admin=db.get(Staff,1)
        if change=='disable':
            admin.active=False
        elif change=='demote':
            admin.role='operator'
        else:
            admin.telegram_id=None if change=='unlink' else '999'
    class Transport:
        async def send_message(self,*args,**kwargs):
            raise AssertionError('Revoked admin must receive no message')
    assert not asyncio.run(bot.send_one(Transport()))
    assert jobs(context)[0].state=='cancelled'


def test_old_assignment_cancelled_after_reassignment(context,monkeypatch):
    monkeypatch.setattr(bot,'SessionLocal',context['factory'])
    with context['factory'].begin() as db:
        admin=db.get(Staff,1)
        operator=db.get(Staff,2)
        operator.telegram_id='222'
        colleague=Staff(name='Коллега',login='colleague',role='operator',active=True,telegram_id='555',password_hash=admin.password_hash)
        db.add(colleague)
        db.flush()
        ticket=create_ticket(db,TicketCreate(**DATA),admin)
        apply_action(db,ticket,TicketAction(action='assign',version=ticket.version,assignee_id=2),admin)
        apply_action(db,ticket,TicketAction(action='assign',version=ticket.version,assignee_id=colleague.id),operator)
    sent=[]
    class Transport:
        async def send_message(self,recipient,text,**kwargs):
            sent.append(recipient)
    while asyncio.run(bot.send_one(Transport())):
        pass
    assert sent==['555']
    assert [row.state for row in jobs(context)]==['cancelled','sent']
