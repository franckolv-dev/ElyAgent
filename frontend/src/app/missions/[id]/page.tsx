"use client";
/**
 * @project    ELY — Exactly Like You
 * @file       frontend/src/app/missions/[id]/page.tsx
 * @brief      Mission detail — plan + timeline + control buttons
 *
 * @author     Franck OLLIVIER <franck.olv@gmail.com>
 * @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
 * @license    PolyForm Strict License 1.0.0
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
} from "lucide-react";
import {
  missionsApi, type Mission, type MissionStep, type MissionPlan,
  STATUS_META, PHASE_META, isTerminal,
} from "@/lib/missions";

export default function MissionDetailPage() {
  const params  = useParams<{ id: string }>();
  const router  = useRouter();
  const id = params?.id as string;

  const [mission, setMission] = useState<Mission | null>(null);
  const [steps, setSteps]     = useState<MissionStep[]>([]);
  const [plan, setPlan]       = useState<MissionPlan | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError]     = useState<string | null>(null);
  const [busy, setBusy]       = useState<string | null>(null); // which action is in flight

  const fetchAll = useCallback(async () => {
    if (!id) return;
    try {
      const [m, s, p] = await Promise.all([
        missionsApi.get(id),
        missionsApi.steps(id),
        missionsApi.plan(id).catch(() => null),
      ]);
      setMission(m);
      setSteps(s);
      setPlan(p);
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
