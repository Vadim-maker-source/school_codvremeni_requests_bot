export class ApiError extends Error { constructor(public status:number, message:string) { super(message); } }
export async function api<T>(path:string, options:RequestInit = {}):Promise<T> {
  const csrf = typeof document === 'undefined' ? '' : document.cookie.split('; ').find(x=>x.startsWith('shkola_csrf='))?.split('=')[1] || '';
  const response = await fetch(`/api${path}`, { ...options, cache:'no-store', credentials:'same-origin', headers:{'Content-Type':'application/json', 'X-CSRF-Token':decodeURIComponent(csrf), ...options.headers} });
  const data = await response.json().catch(()=>({}));
  if (!response.ok) { if(response.status === 401 && path !== '/auth/login') window.dispatchEvent(new Event('session-expired')); throw new ApiError(response.status, data.error?.message || 'Не удалось связаться с сервером'); }
  return data;
}
export type Staff = {id:number;name:string;login:string;role:'admin'|'operator';active:boolean;created_at:string};
export type Item = {id:number;group_id:number;name:string;active:boolean;sort_order:number};
export type Group = {id:number;name:string;active:boolean;sort_order:number;items:Item[]};
export type Status = 'new'|'in_progress'|'completed'|'rejected';
export type Ticket = {id:number;number:string;source:string;created_at:string;updated_at:string;applicant_name:string;contact_snapshot:string;description:string;status:Status;assignee_id:number|null;assignee:Staff|null;group_id:number;item_id:number;group:Group;item:Item;result:string|null;closed_at:string|null;version:number};
export type History = {id:number;created_at:string;action:string;actor_type:string;actor:Staff|null;old_values:Record<string,unknown>;new_values:Record<string,unknown>;comment:string|null};
export type Detail = Ticket & {history:History[];telegram_user_id:string|null;telegram_username:string|null};
export type Page = {items:Ticket[];total:number;page:number;page_size:number};
export type Stats = {total:number;statuses:Record<Status,number>;groups:{name:string;count:number}[];items:{name:string;count:number}[];assignees:{name:string;count:number}[]};
export const statuses:Record<Status,string> = {new:'Новая',in_progress:'В работе',completed:'Выполнена',rejected:'Отклонена'};
export function date(value:string, short=false) { return new Intl.DateTimeFormat('ru-RU', {day:'2-digit',month:short?'short':'long',...(short?{}:{year:'numeric'}),hour:'2-digit',minute:'2-digit',timeZone:'Europe/Moscow'}).format(new Date(value.endsWith('Z')?value:value+'Z')); }
