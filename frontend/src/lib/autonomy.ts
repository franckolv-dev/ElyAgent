import { authFetch } from './auth';
const root = (process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000') + '/api/autonomy';
export async function autonomy<T>(path: string, method = 'GET', body?: unknown): Promise<T> {
  const res = await authFetch(root + path, { method, headers: {'Content-Type':'application/json'}, ...(body === undefined ? {} : {body:JSON.stringify(body)}) });
  const data = await res.json();
  if (!res.ok) throw new Error(typeof data.detail === 'string' ? data.detail : 'La demande n’a pas pu être enregistrée. Vérifie les champs.');
  return data;
}
export type Check = {kind:'tool_success'|'response_contains'|'source_count';value:string;count:number};
export type Rule = {id:string;name:string;source:string;goal:string;enabled:boolean;account:string;daily_limit:number;last_error:string|null;filters:Record<string,string>};
export type Event = {id:string;status:string;mission_id:string|null;summary:string|null;created_at:string};
