"use client";
import { useEffect, useState } from "react";
import { api, type MemoryEntry, type MemorySelection } from "@/lib/api";

export function MemoryContextJournal() {
  const [rows, setRows] = useState<MemorySelection[]>([]);
  const [error, setError] = useState("");
  const [open, setOpen] = useState(false);
  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    api.memorySelections().then(data => {if (!cancelled) setRows(data);}).catch(() => {if (!cancelled) setError("Le journal n’a pas pu être chargé.");});
    return () => {cancelled=true;};
  }, [open]);
  return <section className="card p-4 space-y-3">
    <button aria-expanded={open} className="text-sm text-cyber-cyan" onClick={() => {setError("");setOpen(!open);}}>Utilisé pour cette réponse {open ? "−" : "+"}</button>
    {open && <>
      <p className="text-xs text-text-muted">Derniers contextes préparés pour Ely. Le coût utilise un tokenizer de référence ; il ne représente pas la facturation du modèle.</p>
      {error && <p role="alert" className="text-red-400">{error}</p>}
      {!rows.length && !error && <p className="text-xs text-text-muted">Aucun contexte enregistré pour le moment.</p>}
      {rows.map(row => <details key={row.id} className="border border-border-dim rounded p-3">
        <summary className="text-sm cursor-pointer break-words">{row.query} <span className="text-text-muted text-xs">· {row.tokens} tokens · {row.elapsed_ms} ms</span></summary>
        <p className="text-xs text-text-muted my-2">{new Date(row.created_at).toLocaleString("fr-FR")} · {row.scope ? "Contexte de mission" : "Contexte personnel"}</p>
        {!row.selected.length && <p className="text-xs">Aucun souvenir nécessaire ou retenu.</p>}
        <ul className="space-y-3">{row.selected.map(item => <li key={item.id} className="text-xs break-words"><p className="whitespace-pre-wrap">{item.text}</p><p className="text-text-muted mt-1">{item.source} · {item.reason} · {item.tokens} tokens{item.observed_at && ` · ${item.observed_at}`}</p></li>)}</ul>
      </details>)}
    </>}
  </section>;
}

export function MemoryEditor({family,entry,onSaved}:{family:string;entry:MemoryEntry;onSaved:()=>void}) {
  const [open,setOpen]=useState(false);
  const [content,setContent]=useState(entry.content);
  const [scope,setScope]=useState(entry.metadata.scope || "");
  const [pinned,setPinned]=useState(!!entry.metadata.pinned);
  const [missions,setMissions]=useState<Array<{id:string;label:string}>>([]);
  const [error,setError]=useState("");
  const [saving,setSaving]=useState(false);
  useEffect(() => {
    if (!open) return;
    let cancelled=false;
    api.memoryScopes().then(rows=>{if(!cancelled)setMissions(rows);}).catch(()=>{if(!cancelled)setError("La liste des missions est indisponible. Le périmètre actuel reste conservé.");});
    return ()=>{cancelled=true;};
  },[open]);
  return <>
    <button className="text-xs text-cyber-cyan px-2 py-1" onClick={()=>setOpen(true)}>Corriger</button>
    {open && <div className="fixed inset-0 z-50 bg-black/50 flex items-center justify-center p-4" role="dialog" aria-modal="true" aria-label="Corriger un souvenir">
      <form className="card w-full max-w-lg p-5 space-y-4 max-h-[90vh] overflow-y-auto" onSubmit={async e=>{e.preventDefault();setSaving(true);setError("");try{await api.memoryEdit(family,entry.id,{content,scope,pinned});setOpen(false);onSaved();}catch(e){setError(e instanceof Error?e.message:"Enregistrement impossible.");}finally{setSaving(false);}}}>
        <h2 className="font-medium">Corriger un souvenir</h2>
        <label className="block text-sm">Information à retenir<textarea autoFocus required maxLength={3000} value={content} onChange={e=>setContent(e.target.value)} className="input w-full mt-2 min-h-32" /></label>
        <label className="block text-sm">Utiliser cette information<select className="input w-full mt-2" value={scope} onChange={e=>setScope(e.target.value)}><option value="">Dans mes demandes personnelles</option>{scope && !missions.some(m=>scope===m.id) && <option value={scope}>Périmètre actuel</option>}{missions.map(m=><option key={m.id} value={m.id}>{m.label}</option>)}</select></label>
        <label className="flex gap-2 text-sm"><input type="checkbox" checked={pinned} onChange={e=>setPinned(e.target.checked)} />Prioritaire quand la demande est pertinente</label>
        <p className="text-xs text-text-muted">L’ancienne valeur reste consultable pour une question historique. « Oublier » efface aussi les anciennes versions de cette entrée.</p>
        {error && <p role="alert" className="text-sm text-red-400">{error}</p>}
        <div className="flex justify-end gap-3"><button type="button" disabled={saving} onClick={()=>setOpen(false)}>Annuler</button><button className="btn-primary" disabled={saving || !content.trim()}>{saving?"Enregistrement…":"Enregistrer"}</button></div>
      </form>
    </div>}
  </>;
}
