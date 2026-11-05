"""Execute the exact jury request templates against an isolated migrated SQLite database."""
import importlib.util
from pathlib import Path
import json


def test_burp_jury_demo(context):
    path=Path(__file__).resolve().parents[2]/'scripts'/'prepare-burp-demo.py'
    spec=importlib.util.spec_from_file_location('burp_templates',path)
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    templates=module.templates()
    c=context['anon']
    variables={'PASSWORD_FROM_ENV':'TestAdmin_456!','CHOOSE_EXECUTOR_PASSWORD':'TemporaryJury_456!'}
    def send(name):
        raw=templates[name]
        # Replace longer names before substrings, e.g. OTHER_EXECUTOR_ID before EXECUTOR_ID.
        for key,value in sorted(variables.items(),key=lambda pair:-len(pair[0])):
            raw=raw.replace('{{'+key+'}}',str(value))
        head,body=raw.split('\r\n\r\n',1)
        method,url,_=head.split('\r\n')[0].split(' ')
        headers=dict(line.split(': ',1) for line in head.split('\r\n')[1:])
        if 'Content-Length' in headers:headers['Content-Length']=str(len(body.encode('utf-8')))
        return c.request(method,url,headers=headers,content=body.encode('utf-8'))
    assert send('01-health.txt').status_code==200
    assert send('02-login.txt').status_code==200
    variables.update(SESSION=c.cookies['shkola_session'],CSRF=c.cookies['shkola_csrf'])
    assert send('03-staff.txt').status_code==200
    assert send('04-categories.txt').status_code==200
    response=send('05-create-executor.txt')
    assert response.status_code==201,response.text
    variables['EXECUTOR_ID']=response.json()['id']
    variables['OTHER_EXECUTOR_ID']=2
    response=send('06-create-ticket.txt')
    assert response.status_code==201,response.text
    variables['TICKET_ID']=response.json()['id']
    variables['VERSION']=response.json()['version']
    for name in ('07-take.txt','08-assign.txt','09-reassign.txt','10-complete.txt'):
        response=send(name)
        assert response.status_code==200,(name,response.text)
        variables['VERSION']=response.json()['version']
    response=send('11-ticket-history.txt')
    assert response.status_code==200
    assert [event['action'] for event in response.json()['history']]==['create','take','assign','assign','complete']
    assert send('12-stats.txt').json()['statuses']['completed']==1
    assert send('13-unassigned.txt').json()['total']==0
    variables['EXECUTOR_ID']=2
    assert send('14-executor-tickets.txt').json()['total']==1
    # A clean client ensures no cookie jar silently authenticates the no-session example.
    c.cookies.clear()
    assert send('15-no-session.txt').status_code==401
    assert send('16-no-csrf.txt').status_code==403
