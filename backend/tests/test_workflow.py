from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from datetime import timedelta
import pytest
from sqlalchemy import select, func
from app.models import Ticket, History, Applicant, Notification, Staff, ServerSession, CategoryGroup, CategoryItem, now
from app.schemas import TicketCreate, TicketAction
from app.ticket_service import create_ticket, apply_action
from app.notifications import enqueue
from app.bootstrap import seed

DATA = {'applicant_name':'Анна Петрова','contact':'+7 900 123-45-67','group_id':1,'item_id':1,'description':'Не работает проектор, кабинет 204'}


def new(c, **overrides):
    response = c.post('/api/tickets', json=DATA | overrides)
    assert response.status_code == 201, response.text
    return response.json()


def act(c, ticket, action, **kwargs):
    return c.post(f"/api/tickets/{ticket['id']}/actions", json={'action':action,'version':ticket['version']} | kwargs)


def test_full_workflow_history_stats(context):
    c,a=context['client'](),context['client']('admin')
    t=new(c)
    assert t['source']=='web' and t['number'].startswith('З-')
    assert c.get('/api/tickets',params={'q':t['number']}).json()['total']==1
    detail=c.get(f"/api/tickets/{t['id']}").json()
    assert detail['contact_snapshot']==DATA['contact']
    t=act(c,t,'take').json()
    assert t['status']=='in_progress' and t['assignee']['login']=='operator'
    colleague=a.post('/api/staff',json={'name':'Дежурный оператор','login':'colleague','role':'operator','password':'TestColleague_456!'})
    assert colleague.status_code==201
    colleague_id=colleague.json()['id']
    assert act(c,t,'assign',assignee_id=1).status_code==403
    assert act(c,t,'assign',assignee_id=2).status_code==403
    reassigned=act(c,t,'assign',assignee_id=colleague_id)
    assert reassigned.status_code==200
    t=reassigned.json()
    t=act(c,t,'complete',comment='Заменён кабель HDMI. Проектор работает.').json()
    assert t['status']=='completed' and t['closed_at']
    h=c.get(f"/api/tickets/{t['id']}").json()['history']
    assert [x['action'] for x in h]==['create','take','assign','complete']
    assert h[2]['old_values']['assignee_id']==2 and h[2]['new_values']['assignee_id']==colleague_id
    stats=a.get('/api/stats').json()
    assert stats['total']==1 and stats['statuses']['completed']==1
    assert stats['groups'][0]['count']+stats['groups'][1]['count']+stats['groups'][2]['count']==1
    with context['factory']() as db:
        assert db.scalar(select(func.count()).select_from(Notification))==0


def test_unique_numbers_concurrent_creates(context):
    c=context['client']()
    with ThreadPoolExecutor(max_workers=4) as pool:
        tickets=list(pool.map(lambda _:new(c),range(12)))
    assert len({t['number'] for t in tickets})==12


@pytest.mark.parametrize('field',['applicant_name','contact','description'])
@pytest.mark.parametrize('value',['','   '])
def test_blank_fields(context,field,value):
    c=context['client']()
    assert c.post('/api/tickets',json=DATA|{field:value}).status_code==422


def test_mismatched_category(context):
    c=context['client']()
    assert c.post('/api/tickets',json=DATA|{'item_id':4}).status_code==422


@pytest.mark.parametrize('kind',['group','item'])
def test_inactive_category_preserves_history(context,kind):
    c,a=context['client'](),context['client']('admin')
    t=new(c)
    path='/api/categories/groups/1' if kind=='group' else '/api/categories/items/1'
    assert a.put(path,json={'name':'Переименовано','active':False,'sort_order':4}).status_code==200
    assert c.post('/api/tickets',json=DATA).status_code==422
    assert c.get(f"/api/tickets/{t['id']}").status_code==200


def test_concurrent_take(context):
    c,a=context['client'](),context['client']('admin')
    t=new(c)
    barrier=Barrier(2)
    def run(client):
        barrier.wait()
        return act(client,t,'take')
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(run,[c,a]))
    assert sorted(r.status_code for r in results)==[200,409]
    detail=c.get(f"/api/tickets/{t['id']}").json()
    winner=next(r.json() for r in results if r.status_code==200)
    assert detail['assignee_id']==winner['assignee_id']
    assert len(detail['history'])==2


def test_assign_reassign_noop_and_inactive(context):
    c=context['client']('admin')
    t=new(c)
    t=act(c,t,'assign',assignee_id=2).json()
    assert t['status']=='new'
    assert act(c,t,'assign',assignee_id=2).json()['version']==t['version']
    t=act(c,t,'assign',assignee_id=1).json()
    assert len(c.get(f"/api/tickets/{t['id']}").json()['history'])==3
    with context['factory']() as db:
        db.get(Staff,2).active=False
        db.commit()
    assert act(context['client']('admin'),t,'assign',assignee_id=2).status_code==422


@pytest.mark.parametrize('action',['complete','reject'])
@pytest.mark.parametrize('comment',[None,'','   '])
def test_closing_requires_comment(context,action,comment):
    c=context['client']()
    t=act(c,new(c),'take').json()
    assert act(c,t,action,comment=comment).status_code==422


@pytest.mark.parametrize('action',['complete','reject'])
def test_transition_and_closed_readonly(context,action):
    c=context['client']()
    t=new(c)
    assert act(c,t,action,comment='Причина').status_code==409
    t=act(c,t,'take').json()
    assert act(c,t,'take').status_code==409
    t=act(c,t,action,comment='Результат').json()
    assert t['closed_at'] and t['result']=='Результат'
    for operation in ('take','assign','complete','reject'):
        assert act(c,t,operation,assignee_id=1,comment='Проверка').status_code==409


def test_auth_roles_and_csrf(context):
    c=context['client']()
    anon=context['anon']
    assert anon.get('/api/tickets').status_code==401
    assert c.get('/api/stats').status_code==403
    assert c.post('/api/staff',json={'name':'Тест','login':'third','password':'TestLong_456!'}).status_code==403
    assert c.post('/api/categories/groups',json={'name':'Тест'}).status_code==403
    assert c.post('/api/tickets',json=DATA,headers={'X-CSRF-Token':'wrong'}).status_code==403
    assert c.post('/api/tickets',json=DATA,headers={'Origin':'https://evil.example'}).status_code==403
    assert c.get('/api/auth/me').json().keys()=={'id','name','login','role','active','created_at'}
    assert c.cookies.get('shkola_session')
    assert c.post('/api/tickets',json=DATA|{'telegram_chat_id':'123'}).status_code==422


def test_logout_expiry_and_password_revocation(context):
    c,a=context['client'](),context['client']('admin')
    token=c.cookies['shkola_session']
    assert c.post('/api/auth/logout').status_code==200
    c.cookies.set('shkola_session',token)
    assert c.get('/api/auth/me').status_code==401
    c=context['client']()
    with context['factory']() as db:
        for session in db.scalars(select(ServerSession).where(ServerSession.staff_id==2)):
            session.expires_at=now()-timedelta(seconds=1)
        db.commit()
    assert c.get('/api/auth/me').status_code==401
    c=context['client']()
    assert a.put('/api/staff/2',json={'name':'Новое имя','role':'operator','active':True,'password':'NewPassword_456!'}).status_code==200
    assert c.get('/api/auth/me').status_code==401


def test_deactivation(context):
    c,a=context['client'](),context['client']('admin')
    assert a.put('/api/staff/2',json={'name':'Оператор','role':'operator','active':False}).status_code==200
    assert c.get('/api/tickets').status_code==401
    assert context['anon'].post('/api/auth/login',json={'login':'operator','password':'TestOperator_456!'}).status_code==401


@pytest.mark.parametrize('change',[{'active':False,'role':'admin'},{'active':True,'role':'operator'}])
def test_last_admin(context,change):
    a=context['client']('admin')
    assert a.put('/api/staff/1',json={'name':'Администратор'}|change).status_code==409


def test_login_rate_limit_and_generic_error(context):
    c=context['anon']
    messages=[]
    for i in range(10):
        r=c.post('/api/auth/login',json={'login':'missing' if i%2 else 'admin','password':'wrong'})
        assert r.status_code==401
        messages.append(r.json())
    assert all(x==messages[0] for x in messages)
    assert c.post('/api/auth/login',json={'login':'admin','password':'TestAdmin_456!'}).status_code==429


def test_filters_pagination_stats(context):
    c,a=context['client'](),context['client']('admin')
    tickets=[new(c) for _ in range(4)]
    new(c,group_id=2,item_id=4,description='Протекает потолок')
    act(c,tickets[0],'take')
    assert c.get('/api/tickets',params={'status':'new'}).json()['total']==4
    assert c.get('/api/tickets',params={'group_id':2}).json()['total']==1
    assert c.get('/api/tickets',params={'assignee_id':2}).json()['total']==1
    assert c.get('/api/tickets',params={'q':'НЕ РАБОТАЕТ'}).json()['total']==4
    assert c.get('/api/tickets',params={'date_from':'2099-01-01'}).json()['total']==0
    assert c.get('/api/tickets',params={'page_size':2,'page':2}).json()['items'][0]['id']==3
    assert c.get('/api/tickets',params={'page_size':101}).status_code==422
    assert c.get('/api/tickets',params={'date_from':'2026-11-05','date_to':'2026-01-01'}).status_code==422
    s=a.get('/api/stats').json()
    assert s['total']==5 and s['statuses']['new']==4 and s['statuses']['in_progress']==1


@pytest.mark.parametrize('terminal',['complete','reject'])
def test_telegram_outbox_atomic_idempotent(context,terminal):
    with context['factory']() as db:
        actor=db.get(Staff,2)
        t=create_ticket(db,TicketCreate(**DATA),None,source='telegram',telegram_user_id='789',telegram_chat_id='123')
        apply_action(db,t,TicketAction(action='take',version=t.version),actor)
        apply_action(db,t,TicketAction(action=terminal,version=t.version,comment='Результат'),actor)
        event=db.scalar(select(History).where(History.ticket_id==t.id,History.action==terminal))
        enqueue(db,t,event)
        db.commit()
        notifications=db.scalars(select(Notification)).all()
        assert len(notifications)==2
        assert all(x.state=='pending' and x.sent_at is None and x.attempts==0 for x in notifications)
        assert notifications[0].recipient=='123'
        assert t.source=='telegram'


def test_transaction_rollback(context):
    with context['factory']() as db:
        actor=db.get(Staff,2)
        t=create_ticket(db,TicketCreate(**DATA),None,source='telegram',telegram_chat_id='123')
        apply_action(db,t,TicketAction(action='take',version=t.version),actor)
        db.rollback()
        for model in (Ticket,History,Notification,Applicant):
            assert db.scalar(select(func.count()).select_from(model))==0


def test_contact_snapshot_and_idempotent_seed(context):
    c=context['client']()
    t=new(c)
    with context['factory']() as db:
        ticket=db.get(Ticket,t['id'])
        db.get(Applicant,ticket.applicant_id).contact='Другой контакт'
        db.get(CategoryGroup,1).name='Переименовано'
        db.get(CategoryItem,1).active=False
        old_hash=db.get(Staff,1).password_hash
        seed(db)
        db.commit()
        assert db.scalar(select(func.count()).select_from(CategoryGroup))==3
        assert db.scalar(select(func.count()).select_from(CategoryItem))==9
        assert db.get(CategoryGroup,1).name=='Переименовано'
        assert not db.get(CategoryItem,1).active
        assert db.get(Staff,1).password_hash==old_hash
    assert c.get(f"/api/tickets/{t['id']}").json()['contact_snapshot']==DATA['contact']


def test_admin_crud_and_health(context):
    a=context['client']('admin')
    employee=a.post('/api/staff',json={'name':'Инженер','login':'engineer','password':'LongPassword_456!'}).json()
    assert employee['role']=='operator'
    assert a.put(f"/api/staff/{employee['id']}",json={'name':'Старший инженер','role':'admin','active':True}).status_code==200
    group=a.post('/api/categories/groups',json={'name':'Новая группа','sort_order':9}).json()
    item=a.post(f"/api/categories/groups/{group['id']}/items",json={'name':'Новый элемент'}).json()
    assert item['group_id']==group['id']
    assert a.get('/api/health').json()['status']=='ok'


def test_last_admin_under_concurrent_demotion(context):
    from fastapi.testclient import TestClient
    from app.main import app
    a=context['client']('admin')
    response=a.post('/api/staff',json={'name':'Второй администратор','login':'secondadmin','password':'SecondAdmin_456!','role':'admin'})
    assert response.status_code==201
    second_id=response.json()['id']
    with TestClient(app) as b:
        assert b.post('/api/auth/login',json={'login':'secondadmin','password':'SecondAdmin_456!'}).status_code==200
        b.headers['X-CSRF-Token']=b.cookies['shkola_csrf']
        barrier=Barrier(2)
        def demote(pair):
            client,employee_id=pair
            barrier.wait()
            return client.put(f'/api/staff/{employee_id}',json={'name':'Бывший администратор','role':'operator','active':True})
        with ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(demote,[(a,1),(b,second_id)]))
        assert sorted(r.status_code for r in results)==[200,409]
    with context['factory']() as db:
        assert db.scalar(select(func.count()).select_from(Staff).where(Staff.role=='admin',Staff.active.is_(True)))==1


def test_session_token_is_hashed_and_cookie_protected(context):
    c=context['client']()
    token=c.cookies['shkola_session']
    with context['factory']() as db:
        session=db.scalar(select(ServerSession).where(ServerSession.staff_id==2))
        assert session.token_hash!=token and len(session.token_hash)==64
    response=context['anon'].post('/api/auth/login',json={'login':'operator','password':'TestOperator_456!'})
    session_cookie=next(value for value in response.headers.get_list('set-cookie') if value.startswith('shkola_session='))
    assert 'HttpOnly' in session_cookie and 'SameSite=lax' in session_cookie and 'Max-Age=' in session_cookie


def test_input_length_and_missing_objects(context):
    c=context['client']()
    assert c.post('/api/tickets',json=DATA|{'description':'x'*5001}).status_code==422
    assert c.get('/api/tickets/99999').status_code==404
    assert c.post('/api/tickets',json=DATA|{'group_id':99999}).status_code==422
