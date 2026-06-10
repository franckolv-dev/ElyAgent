"use client";
/**
 * @project    ELY — Exactly Like You
 * @file       frontend/src/app/missions/[id]/page.tsx
 * @brief      Mission detail — plan + timeline + control buttons
 *
 * @author     Franck OLLIVIER <contact@agent-ely.fr>
 * @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
 * @license    Elastic License 2.0
 */

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { AuthGuard } from "@/components/layout/AuthGuard";
import { Sidebar } from "@/components/layout/Sidebar";
import { Header } from "@/components/layout/Header";
import {
  ArrowLeft, Loader2, Play, Pause, X, Zap, AlertCircle, CheckCircle,
  Wrench, Brain, Eye, RefreshCw, ChevronDown, ChevronRight,
  CircleSlash, MessageCircleQuestion, Send, ListChecks,
} from "lucide-react";
import {
  missionsApi, type Mission, type MissionStep, type MissionPlan,
  type MissionStructure, type SpecStepOutline, type StepRun,
  STATUS_META, PHASE_META, isTerminal,
} from "@/lib/missions";

export default function MissionDetailPage() {
  const params  = useParams<{ id: string }>();
  const router  = useRouter();
  const id = params?.id as string;

  const [mission, setMission] = useState<Mission | null>(null);
  const [steps, setSteps]     = useState<MissionStep[]>([]);
  const [plan, setPlan]       = useState<MissionPlan | null>(null);
  // Sprint 4c J4 — outline de la spec + statuts par item (viewer liste)
  const [structure, setStructure] = useState<MissionStructure | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError]     = useState<string | null>(null);
  const [busy, setBusy]       = useState<string | null>(null); // which action is in flight

  const fetchAll = useCallback(async () => {
    if (!id) return;
    try {
      const [m, s, p, st] = await Promise.all([
        missionsApi.get(id),
        missionsApi.steps(id),
        missionsApi.plan(id).catch(() => null),
        missionsApi.structure(id).catch(() => null),
      ]);
      setMission(m);
      setSteps(s);
      setPlan(p);
      setStructure(st && st.steps.length > 0 ? st : null);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Erreur de chargement");
    } finally {
      setLoading(false);
    }
  }, [id]);

  useEffect(() => { fetchAll(); }, [fetchAll]);

  // Auto-refresh while running/planning
  useEffect(() => {
    if (!mission || isTerminal(mission.status)) return;
    if (mission.status === "draft") return;
    const t = setInterval(fetchAll, 3_000);
    return () => clearInterval(t);
  }, [mission, fetchAll]);

  const onTick = async () => {
    if (!id) return;
    setBusy("tick");
    try {
      await missionsApi.tick(id);
      await fetchAll();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Tick échoué");
    } finally { setBusy(null); }
  };
  const onStart = async () => {
    if (!id) return;
    setBusy("start");
    try { await missionsApi.start(id); await fetchAll(); }
    catch (e) { setError(e instanceof Error ? e.message : "Start échoué"); }
    finally { setBusy(null); }
  };
  const onPause = async () => {
    if (!id) return;
    setBusy("pause");
    try { await missionsApi.pause(id); await fetchAll(); }
    catch (e) { setError(e instanceof Error ? e.message : "Pause échoué"); }
    finally { setBusy(null); }
  };
  const onAbort = async () => {
    if (!id) return;
    if (!confirm("Abandonner cette mission ? Cette action est irréversible.")) return;
    setBusy("abort");
    try { await missionsApi.abort(id); await fetchAll(); }
    catch (e) { setError(e instanceof Error ? e.message : "Abort échoué"); }
    finally { setBusy(null); }
  };

  if (loading) {
    return (
      <AuthGuard>
        <div className="flex h-screen overflow-hidden">
          <Sidebar />
          <div className="flex flex-col flex-1 overflow-hidden">
            <Header />
            <div className="flex items-center justify-center flex-1 text-text-muted">
              <Loader2 className="w-5 h-5 animate-spin mr-2" /> Chargement…
            </div>
          </div>
        </div>
      </AuthGuard>
    );
  }

  if (!mission) {
    return (
      <AuthGuard>
        <div className="flex h-screen overflow-hidden">
          <Sidebar />
          <div className="flex flex-col flex-1 overflow-hidden">
            <Header />
            <div className="p-6 text-center text-text-muted text-sm">
              Mission introuvable.
              <button onClick={() => router.push("/missions")} className="ml-2 text-cyber-cyan hover:underline">Retour à la liste</button>
            </div>
          </div>
        </div>
      </AuthGuard>
    );
  }

  const meta     = STATUS_META[mission.status];
  const terminal = isTerminal(mission.status);
  const progress = Math.round((mission.iterations_used / Math.max(1, mission.budget_iterations)) * 100);

  return (
    <AuthGuard>
      <div className="flex h-screen overflow-hidden">
        <Sidebar />
        <div className="flex flex-col flex-1 overflow-hidden">
          <Header />

          <div className="flex-1 overflow-y-auto p-6 space-y-4">
            {/* Back link + title bar */}
            <div className="flex items-center justify-between">
              <Link href="/missions" className="inline-flex items-center gap-1.5 text-xs text-text-muted hover:text-text-primary">
                <ArrowLeft className="w-3.5 h-3.5" /> Toutes les missions
              </Link>
              <button
                onClick={fetchAll}
                disabled={busy !== null}
                className="text-text-muted hover:text-text-primary"
                title="Rafraîchir"
              >
                <RefreshCw className={`w-3.5 h-3.5 ${busy === null ? "" : "animate-spin"}`} />
              </button>
            </div>

            {/* Header card */}
            <div className="bg-bg-secondary border border-border-dim rounded-lg p-4 space-y-3">
              <div className="flex items-start justify-between gap-3">
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 mb-1">
                    <h1 className="text-base font-medium text-text-primary">{mission.title}</h1>
                    <span className={`inline-flex items-center gap-1 text-[10px] px-1.5 py-0.5 rounded border ${meta.color}`}>
                      {meta.emoji} {meta.label}
                    </span>
                  </div>
                  <p className="text-xs text-text-secondary whitespace-pre-wrap">{mission.goal}</p>
                </div>
              </div>

              {/* Stats row */}
              <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-[11px] text-text-muted pt-2 border-t border-border-dim">
                <span>⚙️ Itérations <strong className="text-text-secondary">{mission.iterations_used}</strong>/{mission.budget_iterations}</span>
                <span>🔢 Tokens <strong className="text-text-secondary">{mission.tokens_used.toLocaleString()}</strong>/{mission.budget_tokens.toLocaleString()}</span>
                <span>📅 Créée {new Date(mission.created_at).toLocaleString("fr-FR")}</span>
                {mission.started_at && <span>▶ Démarrée {new Date(mission.started_at).toLocaleString("fr-FR")}</span>}
                {mission.completed_at && <span>⏹ Terminée {new Date(mission.completed_at).toLocaleString("fr-FR")}</span>}
                {mission.tick_interval_seconds && <span>⏱ Heartbeat {mission.tick_interval_seconds}s</span>}
              </div>

              {/* Progress bar */}
              <div className="h-1.5 bg-bg-primary rounded overflow-hidden">
                <div
                  className={`h-full transition-all ${mission.status === "completed" ? "bg-emerald-400" : mission.status === "failed" || mission.status === "aborted" ? "bg-red-400/50" : "bg-cyber-cyan"}`}
                  style={{ width: `${Math.min(100, progress)}%` }}
                />
              </div>

              {/* Final state */}
              {mission.final_summary && (
                <div className="flex items-start gap-2 text-xs text-emerald-300 bg-emerald-500/5 border border-emerald-500/20 rounded px-3 py-2">
                  <CheckCircle className="w-4 h-4 shrink-0 mt-0.5" />
                  <div className="whitespace-pre-wrap">{mission.final_summary}</div>
                </div>
              )}
              {mission.failure_reason && (
                <div className="flex items-start gap-2 text-xs text-red-300 bg-red-500/5 border border-red-500/20 rounded px-3 py-2">
                  <AlertCircle className="w-4 h-4 shrink-0 mt-0.5" />
                  <div className="whitespace-pre-wrap">{mission.failure_reason}</div>
                </div>
              )}

              {error && (
                <div className="flex items-center gap-2 text-xs text-red-400 bg-red-500/10 border border-red-500/20 rounded px-3 py-2">
                  <AlertCircle className="w-4 h-4" /> {error}
                </div>
              )}

              {/* Action buttons */}
              <div className="flex flex-wrap gap-2 pt-1">
                {!terminal && mission.status === "draft" && (
                  <button onClick={onStart} disabled={busy !== null} className="inline-flex items-center gap-1.5 text-xs px-3 py-1.5 rounded border border-emerald-500/30 text-emerald-400 hover:bg-emerald-500/5 disabled:opacity-50">
                    <Play className="w-3.5 h-3.5" /> Démarrer
                  </button>
                )}
                {!terminal && mission.status === "paused" && (
                  <button onClick={onStart} disabled={busy !== null} className="inline-flex items-center gap-1.5 text-xs px-3 py-1.5 rounded border border-emerald-500/30 text-emerald-400 hover:bg-emerald-500/5 disabled:opacity-50">
                    <Play className="w-3.5 h-3.5" /> Reprendre
                  </button>
                )}
                {!terminal && (mission.status === "running" || mission.status === "planning") && (
                  <button onClick={onPause} disabled={busy !== null} className="inline-flex items-center gap-1.5 text-xs px-3 py-1.5 rounded border border-amber-500/30 text-amber-400 hover:bg-amber-500/5 disabled:opacity-50">
                    <Pause className="w-3.5 h-3.5" /> Pause
                  </button>
                )}
                {!terminal && (
                  <button onClick={onTick} disabled={busy !== null} className="inline-flex items-center gap-1.5 text-xs px-3 py-1.5 rounded border border-cyber-cyan/30 text-cyber-cyan hover:bg-cyber-cyan/5 disabled:opacity-50">
                    {busy === "tick" ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Zap className="w-3.5 h-3.5" />}
                    {busy === "tick" ? "Tick en cours…" : "Tick manuel"}
                  </button>
                )}
                {!terminal && (
                  <button onClick={onAbort} disabled={busy !== null} className="inline-flex items-center gap-1.5 text-xs px-3 py-1.5 rounded border border-cyber-red/30 text-cyber-red hover:bg-cyber-red/5 disabled:opacity-50">
                    <X className="w-3.5 h-3.5" /> Abandonner
                  </button>
                )}
              </div>
            </div>

            {/* Plan card */}
            {structure && (
              <StructuredRunPanel
                structure={structure}
                missionId={mission.id}
                onAnswered={fetchAll}
              />
            )}

            {plan && (
              <div className="bg-bg-secondary border border-border-dim rounded-lg p-4">
                <div className="flex items-center gap-2 mb-3">
                  <Brain className="w-4 h-4 text-purple-400" />
                  <h2 className="text-sm font-medium text-text-primary">Plan v{plan.version}</h2>
                  {plan.reason_for_replan && (
                    <span className="text-[10px] px-1.5 py-0.5 rounded bg-pink-500/10 border border-pink-500/20 text-pink-400">
                      Replan : {plan.reason_for_replan.slice(0, 60)}
                    </span>
                  )}
                </div>
                {plan.plan_json?.steps && plan.plan_json.steps.length > 0 ? (
                  <ul className="space-y-1.5">
                    {plan.plan_json.steps.map((s) => (
                      <li key={s.id} className="flex items-start gap-2 text-xs">
                        <span className="shrink-0 mt-0.5">
                          {s.status === "done" ? "✅" : s.status === "failed" ? "❌" : "⏳"}
                        </span>
                        <div className="flex-1 min-w-0">
                          <span className="text-text-secondary">{s.description}</span>
                          {s.tool_hint && (
                            <span className="ml-2 text-[10px] text-text-muted">→ <code className="text-cyber-cyan">{s.tool_hint}</code></span>
                          )}
                        </div>
                      </li>
                    ))}
                  </ul>
                ) : (
                  <pre className="text-[11px] text-text-secondary whitespace-pre-wrap font-mono">{plan.plan_text}</pre>
                )}
              </div>
            )}

            {/* Timeline */}
            <div className="bg-bg-secondary border border-border-dim rounded-lg p-4">
              <h2 className="text-sm font-medium text-text-primary mb-3 flex items-center gap-2">
                <Eye className="w-4 h-4 text-cyber-cyan" /> Timeline ({steps.length} étapes)
              </h2>
              {steps.length === 0 ? (
                <p className="text-xs text-text-muted">Aucune étape encore. Lance un tick pour démarrer.</p>
              ) : (
                <div className="space-y-2">
                  {steps.map((s) => <StepRow key={s.id} step={s} />)}
                </div>
              )}
            </div>
          </div>
        </div>
      </div>
    </AuthGuard>
  );
}

// ── One step in the timeline ────────────────────────────────────────────────

function StepRow({ step }: { step: MissionStep }) {
  const meta = PHASE_META[step.phase];
  const [open, setOpen] = useState(false);
  const hasDetails = !!(step.tool_input || step.tool_output || step.thought || step.evaluation);

  return (
    <div className="border border-border-dim rounded bg-bg-primary/40">
      <button
        onClick={() => hasDetails && setOpen(!open)}
        disabled={!hasDetails}
        className={`w-full flex items-center gap-2 px-3 py-2 text-left ${hasDetails ? "hover:bg-bg-primary/60" : ""}`}
      >
        <span className="text-[10px] text-text-muted w-7 text-right shrink-0">#{step.iteration}</span>
        <span className={`text-[10px] uppercase font-medium w-14 ${meta.color} shrink-0`}>{meta.label}</span>
        {step.tool_name && (
          <span className="inline-flex items-center gap-1 text-[10px] text-cyber-cyan bg-cyber-cyan/5 border border-cyber-cyan/20 rounded px-1.5 py-0.5 shrink-0">
            <Wrench className="w-2.5 h-2.5" /> {step.tool_name}
          </span>
        )}
        <span className="flex-1 text-[11px] text-text-secondary truncate">
          {step.evaluation || step.thought || step.tool_output || "(no description)"}
        </span>
        {step.success === true && <CheckCircle className="w-3 h-3 text-emerald-400 shrink-0" />}
        {step.success === false && <AlertCircle className="w-3 h-3 text-red-400 shrink-0" />}
        <span className="text-[10px] text-text-muted shrink-0">{step.duration_ms}ms</span>
        {hasDetails && (open ? <ChevronDown className="w-3 h-3 text-text-muted" /> : <ChevronRight className="w-3 h-3 text-text-muted" />)}
      </button>

      {open && hasDetails && (
        <div className="border-t border-border-dim px-3 py-2 space-y-2 text-[11px]">
          {step.thought && (
            <div>
              <div className="text-text-muted text-[10px] uppercase mb-0.5">Thought</div>
              <pre className="text-text-secondary whitespace-pre-wrap font-mono text-[11px] bg-bg-primary/50 rounded p-2">{step.thought}</pre>
            </div>
          )}
          {step.tool_input && (
            <div>
              <div className="text-text-muted text-[10px] uppercase mb-0.5">Tool input</div>
              <pre className="text-cyber-cyan whitespace-pre-wrap font-mono text-[11px] bg-bg-primary/50 rounded p-2">{JSON.stringify(step.tool_input, null, 2)}</pre>
            </div>
          )}
          {step.tool_output && (
            <div>
              <div className="text-text-muted text-[10px] uppercase mb-0.5">Tool output</div>
              <pre className="text-text-secondary whitespace-pre-wrap font-mono text-[11px] bg-bg-primary/50 rounded p-2 max-h-60 overflow-y-auto">{step.tool_output}</pre>
            </div>
          )}
          {step.evaluation && (
            <div>
              <div className="text-text-muted text-[10px] uppercase mb-0.5">Évaluation</div>
              <p className="text-text-secondary">{step.evaluation}</p>
            </div>
          )}
          {step.model_used && (
            <div className="text-[10px] text-text-muted">
              Modèle : <code className="text-cyber-cyan">{step.model_used}</code>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ── Sprint 4c J4 — viewer LISTE de la mission structurée ────────────────────
// Le backlog est explicite : « PAS un canvas n8n — juste visualiser comment
// la mission s'exécute ». Une liste de steps, les items dessous, et le champ
// de réponse inline sur les ⏸ — clic, réponse, la mission repart.

const RUN_ICON: Record<StepRun["status"], { icon: typeof CheckCircle; cls: string; label: string }> = {
  done:         { icon: CheckCircle,            cls: "text-emerald-400", label: "terminé" },
  running:      { icon: Loader2,                cls: "text-cyber-cyan animate-spin", label: "en cours" },
  pending:      { icon: ChevronRight,           cls: "text-text-muted", label: "à traiter" },
  waiting_user: { icon: MessageCircleQuestion,  cls: "text-amber-400", label: "attend ta réponse" },
  skipped:      { icon: CircleSlash,            cls: "text-text-muted", label: "sauté" },
  failed:       { icon: AlertCircle,            cls: "text-red-400", label: "échec" },
};

function stepSummary(runs: StepRun[]): { done: number; total: number; waiting: number } {
  const terminal = new Set(["done", "skipped", "failed"]);
  return {
    done: runs.filter((r) => terminal.has(r.status)).length,
    total: runs.length,
    waiting: runs.filter((r) => r.status === "waiting_user").length,
  };
}

function AnswerBox({ missionId, run, onAnswered }: {
  missionId: string; run: StepRun; onAnswered: () => void;
}) {
  const [value, setValue] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const submit = async () => {
    if (!value.trim()) return;
    setBusy(true);
    setErr(null);
    try {
      await missionsApi.answerStepRun(missionId, run.step_id, run.item_index, value.trim());
      setValue("");
      onAnswered();
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Envoi échoué");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="mt-1.5 ml-6">
      <div className="flex gap-1.5">
        <input
          type="text"
          value={value}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter") submit(); }}
          placeholder="Ta réponse… (Entrée pour envoyer)"
          className="flex-1 text-xs bg-bg-secondary border border-amber-500/30 rounded px-2.5 py-1.5 text-text-primary placeholder:text-text-muted focus:outline-none focus:border-amber-400/60"
        />
        <button
          onClick={submit}
          disabled={busy || !value.trim()}
          className="inline-flex items-center gap-1 text-xs px-2.5 py-1.5 rounded border border-amber-500/30 text-amber-400 hover:bg-amber-500/10 disabled:opacity-50"
        >
          {busy ? <Loader2 className="w-3 h-3 animate-spin" /> : <Send className="w-3 h-3" />}
          Répondre
        </button>
      </div>
      {err && <p className="text-[10px] text-red-400 mt-1">{err}</p>}
    </div>
  );
}

function RunRow({ missionId, run, onAnswered }: {
  missionId: string; run: StepRun; onAnswered: () => void;
}) {
  const meta = RUN_ICON[run.status] ?? RUN_ICON.pending;
  const Icon = meta.icon;
  return (
    <li className="py-1">
      <div className="flex items-start gap-2 text-xs">
        <Icon className={`w-3.5 h-3.5 shrink-0 mt-0.5 ${meta.cls}`} />
        <div className="flex-1 min-w-0">
          <span className={`${run.status === "skipped" ? "text-text-muted line-through" : "text-text-secondary"}`}>
            {run.item_value ?? "(step)"}
          </span>
          {run.note && (
            <span className={`ml-2 ${run.status === "waiting_user" ? "text-amber-300" : "text-text-muted"}`}>
              {run.status === "waiting_user" ? "⚠ " : "— "}{run.note}
            </span>
          )}
          {run.status === "done" && run.output && (
            <span className="ml-2 text-text-muted">— {run.output.slice(0, 120)}</span>
          )}
          {run.answer && run.status !== "waiting_user" && (
            <span className="ml-2 text-cyber-cyan/80" title="Ta réponse a guidé ce traitement">
              ↳ {run.answer.slice(0, 80)}
            </span>
          )}
        </div>
      </div>
      {run.status === "waiting_user" && (
        <AnswerBox missionId={missionId} run={run} onAnswered={onAnswered} />
      )}
    </li>
  );
}

function StructuredRunPanel({ structure, missionId, onAnswered }: {
  structure: MissionStructure; missionId: string; onAnswered: () => void;
}) {
  const runsByStep = new Map<string, StepRun[]>();
  for (const r of structure.runs) {
    const list = runsByStep.get(r.step_id) ?? [];
    list.push(r);
    runsByStep.set(r.step_id, list);
  }
  const totalWaiting = structure.runs.filter((r) => r.status === "waiting_user").length;

  const stepIcon = (step: SpecStepOutline, runs: StepRun[]) => {
    if (runs.length === 0) return { icon: ChevronRight, cls: "text-text-muted" };
    const { done, total, waiting } = stepSummary(runs);
    if (waiting > 0) return { icon: MessageCircleQuestion, cls: "text-amber-400" };
    if (done === total) return { icon: CheckCircle, cls: "text-emerald-400" };
    return { icon: Loader2, cls: "text-cyber-cyan animate-spin" };
  };

  return (
    <div className="bg-bg-primary border border-border-dim rounded-lg p-4">
      <div className="flex items-center gap-2 mb-3">
        <ListChecks className="w-4 h-4 text-cyber-cyan" />
        <h2 className="text-sm font-medium text-text-primary">Exécution structurée</h2>
        {totalWaiting > 0 && (
          <span className="ml-auto text-[11px] px-2 py-0.5 rounded border border-amber-500/30 text-amber-300 bg-amber-500/10">
            {totalWaiting} question{totalWaiting > 1 ? "s" : ""} en attente
          </span>
        )}
      </div>
      <ul className="space-y-2">
        {structure.steps.map((step) => {
          const runs = runsByStep.get(step.id) ?? [];
          const { done, total } = stepSummary(runs);
          const isForeach = !!step.foreach;
          const meta = stepIcon(step, runs);
          const Icon = meta.icon;
          return (
            <li key={step.id}>
              <div className="flex items-start gap-2">
                <Icon className={`w-4 h-4 shrink-0 mt-0.5 ${meta.cls}`} />
                <div className="flex-1 min-w-0">
                  <code className="text-xs font-medium text-text-primary">{step.id}</code>
                  {isForeach && total > 0 && (
                    <span className="ml-2 text-[11px] text-text-muted">{done}/{total}</span>
                  )}
                  <p className="text-[11px] text-text-muted line-clamp-1">{step.do}</p>
                  {step.handler_cases.length > 0 && (
                    <p className="text-[10px] text-text-muted/70">
                      cas prévus : {step.handler_cases.join(", ")}
                    </p>
                  )}
                </div>
              </div>
              {/* Items (foreach) ou run unique avec note */}
              {runs.length > 0 && (isForeach || runs.some((r) => r.note || r.status === "waiting_user")) && (
                <ul className="ml-6 mt-1 border-l border-border-dim pl-3">
                  {runs.map((r) => (
                    <RunRow
                      key={`${r.step_id}:${r.item_index}`}
                      missionId={missionId}
                      run={r}
                      onAnswered={onAnswered}
                    />
                  ))}
                </ul>
              )}
            </li>
          );
        })}
      </ul>
    </div>
  );
}
