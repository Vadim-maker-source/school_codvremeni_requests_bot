"""Generate public request templates. No credentials or active sessions are embedded."""
from pathlib import Path
import json

ROOT=Path(__file__).resolve().parents[1]
DESTINATION=ROOT/'docs'/'burp-requests'


def request(method, path, body=None, auth=True, csrf=True):
    headers=['Host: 127.0.0.1:8000','Connection: close']
    if auth:
        headers.append('Cookie: shkola_session={{SESSION}}; shkola_csrf={{CSRF}}')
    if csrf and auth:
        headers.append('X-CSRF-Token: {{CSRF}}')
    payload='' if body is None else json.dumps(body,ensure_ascii=False,separators=(',',':'))
    # Numeric placeholders must be replaced by numbers before sending.
    for placeholder in ('VERSION','EXECUTOR_ID','OTHER_EXECUTOR_ID'):
        payload=payload.replace('"'+placeholder+'"','{{'+placeholder+'}}')
    for placeholder in ('PASSWORD_FROM_ENV','CHOOSE_EXECUTOR_PASSWORD'):
        payload=payload.replace('"'+placeholder+'"','"{{'+placeholder+'}}"')
    for placeholder in ('TICKET_ID','EXECUTOR_ID'):
        path=path.replace(placeholder,'{{'+placeholder+'}}')
    if body is not None:
        headers.extend(['Content-Type: application/json',f'Content-Length: {len(payload.encode("utf-8"))}'])
    return '\r\n'.join([f'{method} {path} HTTP/1.1',*headers,'',payload])


def templates():
    return {
        '01-health.txt':request('GET','/api/health',auth=False),
        '02-login.txt':request('POST','/api/auth/login',{'login':'admin','password':'PASSWORD_FROM_ENV'},auth=False),
        '03-staff.txt':request('GET','/api/staff'),
        '04-categories.txt':request('GET','/api/categories'),
        '05-create-executor.txt':request('POST','/api/staff',{'name':'Исполнитель демонстрации','login':'jury_executor','password':'CHOOSE_EXECUTOR_PASSWORD','role':'operator'}),
        '06-create-ticket.txt':request('POST','/api/tickets',{'applicant_name':'Демонстрационный заявитель','contact':'demo@example.invalid','group_id':1,'item_id':1,'description':'Не работает проектор в кабинете 204'}),
        '07-take.txt':request('POST','/api/tickets/TICKET_ID/actions',{'action':'take','version':'VERSION'}),
        '08-assign.txt':request('POST','/api/tickets/TICKET_ID/actions',{'action':'assign','assignee_id':'EXECUTOR_ID','version':'VERSION'}),
        '09-reassign.txt':request('POST','/api/tickets/TICKET_ID/actions',{'action':'assign','assignee_id':'OTHER_EXECUTOR_ID','version':'VERSION'}),
        '10-complete.txt':request('POST','/api/tickets/TICKET_ID/actions',{'action':'complete','version':'VERSION','comment':'Заменён кабель HDMI. Проектор проверен и работает.'}),
        '11-ticket-history.txt':request('GET','/api/tickets/TICKET_ID'),
        '12-stats.txt':request('GET','/api/stats'),
        '13-unassigned.txt':request('GET','/api/tickets?assignee_id=0&page=1&page_size=15'),
        '14-executor-tickets.txt':request('GET','/api/tickets?assignee_id=EXECUTOR_ID&page=1&page_size=15'),
        '15-no-session.txt':request('GET','/api/tickets',auth=False),
        '16-no-csrf.txt':request('POST','/api/tickets',{'applicant_name':'Демонстрационный заявитель','contact':'demo@example.invalid','group_id':1,'item_id':1,'description':'Проверка CSRF'},csrf=False),
    }


if __name__=='__main__':
    DESTINATION.mkdir(parents=True,exist_ok=True)
    for name,text in templates().items():
        (DESTINATION/name).write_bytes(text.encode('utf-8'))
    print(f'Prepared {len(templates())} request templates in docs/burp-requests')
