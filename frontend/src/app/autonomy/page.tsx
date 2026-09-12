'use client';
import {useCallback,useEffect,useState} from 'react';
import Link from 'next/link';
import {AuthGuard} from '@/components/layout/AuthGuard';
import {Sidebar} from '@/components/layout/Sidebar';
import {Header} from '@/components/layout/Header';
import {autonomy, type Rule, type Event} from '@/lib/autonomy';
import {AutonomyControl} from './controls';
import {CriteriaEditor} from './criteria';
import {type Check} from '@/lib/autonomy';
const sources: Record<string,string> = {'gmail.received':'Nouveau mail Gmail','calendar.changed':'Modification de l’agenda principal','file.indexed':'Nouveau document indexé'};
const statuses: Record<string,string> = {planning:'Préparation',running:'En cours',waiting_user:'Décision attendue',paused:'En pause',completed:'Terminée',failed:'Échec',aborted:'Arrêtée',pending:'En attente du quota',cancelled:'Annulé'};
const initial = {name:'',source:'gmail.received',account:'default',goal:'',sender_contains:'',text_contains:'',folder_prefix:'',daily_limit:5};
export default function Page() {
  const [checks,setChecks]=useState<Check[]>([]);
  const [tab,setTab]=useState('rules'),[rules,setRules]=useState<Rule[]>([]),[events,setEvents]=useState<Event[]>([]);
  const [form,setForm]=useState(initial),[busy,setBusy]=useState(false),[error,setError]=useState(''),[notice,setNotice]=useState(''),[loading,setLoading]=useState(true);
  const [preview,setPreview]=useState(''),[sample,setSample]=useState({sender:'',text:'',path:''});
  const refresh=useCallback(async()=>{try {const [r,e]=await Promise.all([autonomy<Rule[]>('/rules'),autonomy<Event[]>('/events')]);setRules(r);setEvents(e);}catch(e){setError(String(e instanceof Error?e.message:e));}finally{setLoading(false);}},[]);
  useEffect(()=>{void refresh();const timer=setInterval(refresh,15000);return()=>clearInterval(timer);},[refresh]);
  async function act(fn:()=>Promise<void>){setBusy(true);setError('');setNotice('');try {await fn();await refresh();}catch(e){setError(e instanceof Error?e.message:String(e));}finally{setBusy(false);}}
  return <AuthGuard><div className="flex h-screen overflow-hidden"><Sidebar/><div className="flex flex-col flex-1 min-w-0"><Header/><main className="overflow-y-auto p-4 md:p-6 space-y-5 text-text-primary">
    <div><h1 className="text-xl font-semibold">Autonomie</h1><p className="text-sm text-text-muted mt-1">Des déclencheurs précis, des résultats vérifiables et des limites que tu choisis.</p></div>
    <nav aria-label="Sections autonomie" className="flex flex-wrap gap-2">{[['rules','Automatismes'],['follow','Suivi'],['permissions','Autorisations'],['procedures','Procédures']].map(([id,label])=><button className={`btn ${tab===id?'primary':''}`} aria-pressed={tab===id} key={id} onClick={()=>setTab(id)}>{label}</button>)}</nav>
    {error&&<p role="alert" className="text-red-300">{error}</p>}{notice&&<p role="status" className="text-cyber-cyan">{notice}</p>}
    {tab==='rules'&&<><form className="card p-4 grid md:grid-cols-2 gap-4" onSubmit={e=>{e.preventDefault();void act(async()=>{await autonomy('/rules','POST',{...form,checks});setForm(initial);setChecks([]);setNotice('Automatisme enregistré en pause. Simule-le puis active-le.');});}}>
      <h2 className="font-medium md:col-span-2">Nouvel automatisme</h2>
      <label>Nom<input required maxLength={160} value={form.name} onChange={e=>setForm({...form,name:e.target.value})}/></label>
      <label>Quand<select value={form.source} onChange={e=>setForm({...form,source:e.target.value,sender_contains:'',folder_prefix:''})}>{Object.entries(sources).map(([id,label])=><option key={id} value={id}>{label}</option>)}</select></label>
      {form.source!=='file.indexed'&&<label>Compte Google (alias)<input value={form.account} required onChange={e=>setForm({...form,account:e.target.value})}/></label>}
      {form.source==='gmail.received'&&<label>L’expéditeur contient<input value={form.sender_contains} onChange={e=>setForm({...form,sender_contains:e.target.value})}/></label>}
      {form.source==='file.indexed'&&<label>Dossier (facultatif)<input placeholder="/Users/…/Documents" value={form.folder_prefix} onChange={e=>setForm({...form,folder_prefix:e.target.value})}/></label>}
      <label>Le titre contient (facultatif)<input value={form.text_contains} onChange={e=>setForm({...form,text_contains:e.target.value})}/></label>
      <label>Maximum de missions par jour (UTC)<input type="number" min={1} max={50} required value={form.daily_limit} onChange={e=>setForm({...form,daily_limit:Number(e.target.value)})}/></label>
      <label className="md:col-span-2">Alors, Ely doit…<textarea required minLength={5} maxLength={8000} rows={3} placeholder="Résumer cette facture et la classer dans mon dossier…" value={form.goal} onChange={e=>setForm({...form,goal:e.target.value})}/></label>
      <p className="text-xs text-text-muted md:col-span-2">Vérification chaque minute, sans appel au modèle. Seuls les événements postérieurs à l’activation sont pris en compte. Les fichiers doivent d’abord être indexés dans Connaissances.</p>
      <div className="md:col-span-2"><CriteriaEditor value={checks} onChange={setChecks}/></div>
      <button disabled={busy} className="btn primary justify-self-start">Enregistrer en pause</button>
    </form>
    {loading?<p role="status">Chargement…</p>:rules.length===0?<p>Aucun automatisme enregistré.</p>:rules.map(r=><article className="card p-4 space-y-3" key={r.id}><div className="flex flex-wrap justify-between gap-3"><div><h2 className="font-medium">{r.name}</h2><p className="text-xs text-text-muted">{sources[r.source]} · {r.enabled?'Actif':'En pause'} · {r.daily_limit}/jour</p></div><div className="flex gap-2"><button disabled={busy} className="btn" onClick={()=>{setPreview(preview===r.id?'':r.id);setNotice('');}}>Simuler</button><button disabled={busy} className="btn primary" onClick={()=>void act(async()=>{await autonomy(`/rules/${r.id}/enabled`,'PUT',{enabled:!r.enabled});})}>{r.enabled?'Mettre en pause':'Activer'}</button></div></div><p className="text-sm whitespace-pre-wrap break-words">{r.goal}</p>{r.last_error&&<p role="alert" className="text-amber-300">{r.last_error}</p>}{preview===r.id&&<div className="grid md:grid-cols-3 gap-3"><label>Expéditeur d’essai<input value={sample.sender} onChange={e=>setSample({...sample,sender:e.target.value})}/></label><label>Titre d’essai<input value={sample.text} onChange={e=>setSample({...sample,text:e.target.value})}/></label><label>Chemin d’essai<input value={sample.path} onChange={e=>setSample({...sample,path:e.target.value})}/></label><button className="btn" disabled={busy} onClick={()=>void act(async()=>{const res=await autonomy<{matches:boolean}>(`/rules/${r.id}/preview`,'POST',sample);setNotice(res.matches?'Les conditions correspondent. Cette simulation n’a exécuté aucune action.':'Les conditions ne correspondent pas. Aucune action exécutée.');})}>Tester les conditions</button></div>}</article>)}</>}
    {tab==='follow'&&<><AutonomyControl section="follow"/>{events.length>0&&<h2 className="font-medium">Derniers événements</h2>}{events.map(e=><article key={e.id} className="card p-4"><p>{statuses[e.status]||e.status} · {new Date(e.created_at).toLocaleString('fr-FR')}</p>{e.summary&&<p className="text-sm mt-2 whitespace-pre-wrap">{e.summary}</p>}{e.mission_id&&<Link className="text-cyber-cyan underline" href={`/missions/${e.mission_id}`}>Voir la mission</Link>}</article>)}</>}
    {(tab==='permissions'||tab==='procedures')&&<AutonomyControl section={tab}/>}
    <style jsx>{`label{display:flex;flex-direction:column;gap:6px;font-size:13px}input,select,textarea{width:100%;min-width:0;border:1px solid var(--border-subtle);border-radius:8px;background:var(--bg-app);color:inherit;padding:10px}input:focus,textarea:focus,select:focus{outline:2px solid var(--accent,#91b9ff);outline-offset:2px}`}</style>
  </main></div></div></AuthGuard>;
}
