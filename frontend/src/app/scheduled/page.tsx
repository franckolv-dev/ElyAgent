"use client";
/**
 * @project    ELY — Exactly Like You
 * @file       frontend/src/app/scheduled/page.tsx
 * @brief      Tâches planifiées — liste + suppression RÉELLE + activer/
 *             désactiver + exécuter maintenant. Comble le manque d'UI qui
 *             rendait les tâches cron de l'agent invisibles (bug 13/06).
 *
 * @author     Franck OLLIVIER <contact@agent-ely.fr>
 * @copyright  Copyright (c) 2025-2026 Franck OLLIVIER
 * @license    MIT
 *            https://opensource.org/licenses/MIT
 */

import { useCallback, useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { AuthGuard } from "@/components/layout/AuthGuard";
import { Sidebar } from "@/components/layout/Sidebar";
import { Header } from "@/components/layout/Header";
import {
  Clock, Loader2, AlertCircle, Trash2, Play, Power, RefreshCw, X, Lightbulb, Plus, Target,
} from "lucide-react";
import {
  schedulerApi, describeCron, cadenceToCron, type ScheduledTask,
} from "@/lib/scheduler";
import { api, type AnticipationSuggestion } from "@/lib/api";

/** C5 — prefill carried from a suggestion into the create modal. */
interface CreatePrefill {
  suggestionId: number | null;
  name: string;
  prompt: string;
  cron: string;
  // Lancer une MISSION à l'heure dite plutôt qu'un tour de chat : pour un
  // travail long (tri d'une boîte, prospection), qui a besoin de carnet,
  // budgets et passages (04/09).
  asMission: boolean;
}

export default function ScheduledTasksPage() {
  const t = useTranslations("scheduled");
  const [tasks, setTasks]     = useState<ScheduledTask[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError]     = useState<string | null>(null);
  const [toast, setToast]     = useState<{ kind: "ok" | "err"; msg: string } | null>(null);
  const [confirmId, setConfirmId] = useState<string | null>(null);
  const [busyId, setBusyId]   = useState<string | null>(null);
  // C5 — anticipation suggestions (proposed only) + create modal state.
  const [suggestions, setSuggestions] = useState<AnticipationSuggestion[]>([]);
  const [prefill, setPrefill] = useState<CreatePrefill | null>(null);
  const [creating, setCreating] = useState(false);
  const [suggestionBusy, setSuggestionBusy] = useState<number | null>(null);

  const flash = (kind: "ok" | "err", msg: string) => {
    setToast({ kind, msg });
    setTimeout(() => setToast(null), 3500);
  };

  const fetchAll = useCallback(async () => {
    setError(null);
    try {
      setTasks(await schedulerApi.list());
    } catch (e) {
      setError(e instanceof Error ? e.message : t("loadError"));
    } finally {
      setLoading(false);
    }
  }, [t]);

  useEffect(() => { fetchAll(); }, [fetchAll]);

  // C5 — load actionable suggestions once (weekly detector → no polling).
  const fetchSuggestions = useCallback(async () => {
    try {
      const out = await api.mySuggestionsList("proposed");
      setSuggestions(out.suggestions);
    } catch {
      // Best-effort : le bandeau est optionnel, jamais bloquant.
      setSuggestions([]);
    }
  }, []);
  useEffect(() => { fetchSuggestions(); }, [fetchSuggestions]);

  const onSuggestionDismiss = async (s: AnticipationSuggestion) => {
    setSuggestionBusy(s.id);
    try {
      await api.mySuggestionDismiss(s.id);
      await fetchSuggestions();
      flash("ok", t("suggestionDismissed"));
    } catch (e) {
      flash("err", e instanceof Error ? e.message : t("actionError"));
    } finally {
      setSuggestionBusy(null);
    }
  };

  const openCreateFromSuggestion = (s: AnticipationSuggestion) => {
    setPrefill({
      suggestionId: s.id,
      name: s.suggested_prompt.slice(0, 60),
      prompt: s.suggested_prompt,
      cron: cadenceToCron(s.suggested_cadence) ?? "",
      asMission: false,
    });
  };

  // Le formulaire existait mais ne s'ouvrait que depuis une suggestion :
  // sans ce bouton, créer une tâche à la main passait par le chat (04/09).
  const openCreateBlank = () => {
    setPrefill({ suggestionId: null, name: "", prompt: "", cron: "", asMission: false });
  };

  const onCreate = async () => {
    if (!prefill || !prefill.name.trim() || !prefill.prompt.trim() || !prefill.cron.trim()) return;
    setCreating(true);
    try {
      await schedulerApi.create({
        name: prefill.name.trim(),
        prompt: prefill.prompt.trim(),
        cron_expression: prefill.cron.trim(),
        as_mission: prefill.asMission,
      });
      // La tâche est créée PAR L'UTILISATEUR — on marque la suggestion
      // acceptée seulement après ce succès (best-effort).
      if (prefill.suggestionId !== null) {
        try { await api.mySuggestionAccept(prefill.suggestionId); } catch { /* non bloquant */ }
      }
      setPrefill(null);
      await Promise.all([fetchAll(), fetchSuggestions()]);
      flash("ok", t("toastCreated"));
    } catch (e) {
      flash("err", e instanceof Error ? e.message : t("createError"));
    } finally {
      setCreating(false);
    }
  };

  // Polling : rafraîchit toutes les 5 s tant qu'au moins une tâche est « en
  // cours », pour que l'utilisateur voie running → réussi/échec en direct.
  useEffect(() => {
    const anyRunning = tasks.some((t) => t.last_status === "running");
    const id = setInterval(fetchAll, anyRunning ? 4000 : 15000);
    return () => clearInterval(id);
  }, [tasks, fetchAll]);

  const onToggle = async (task: ScheduledTask) => {
    setBusyId(task.id);
    try {
      await schedulerApi.setEnabled(task.id, !task.enabled);
      await fetchAll();
      flash("ok", task.enabled ? t("toastDisabled") : t("toastEnabled"));
    } catch (e) {
      flash("err", e instanceof Error ? e.message : t("actionError"));
    } finally {
      setBusyId(null);
    }
  };

  const onRun = async (task: ScheduledTask) => {
    setBusyId(task.id);
    try {
      const r = await schedulerApi.runNow(task.id);
      flash("ok", r.message || t("toastRun"));
    } catch (e) {
      flash("err", e instanceof Error ? e.message : t("actionError"));
    } finally {
      setBusyId(null);
    }
  };

  const onDelete = async (task: ScheduledTask) => {
    setBusyId(task.id);
    try {
      await schedulerApi.remove(task.id);
      setConfirmId(null);
      await fetchAll();
      flash("ok", t("toastDeleted"));
    } catch (e) {
      flash("err", e instanceof Error ? e.message : t("actionError"));
    } finally {
      setBusyId(null);
    }
  };

  return (
    <AuthGuard>
      <div className="flex h-screen overflow-hidden">
        <Sidebar />
        <div className="flex flex-col flex-1 min-w-0 overflow-hidden">
        <Header />
        <div className="flex flex-1 overflow-hidden">
          <main className="flex-1 overflow-y-auto p-6 space-y-4" style={{ background: "var(--bg-app)" }}>

            {/* Header */}
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-3">
                <Clock className="w-5 h-5 text-cyber-cyan" />
                <h1 className="text-lg font-medium text-text-primary">{t("title")}</h1>
                <span className="text-[11px] text-text-muted">({tasks.length})</span>
              </div>
              <div className="flex items-center gap-2">
                <button
                  onClick={openCreateBlank}
                  className="text-[11px] px-3 py-1.5 rounded border border-cyber-cyan/30 bg-cyber-cyan/10 text-cyber-cyan hover:bg-cyber-cyan/20 inline-flex items-center gap-1.5"
                >
                  <Plus className="w-3.5 h-3.5" />
                  {t("createNew")}
                </button>
                <button onClick={() => { setLoading(true); fetchAll(); }} className="btn" title={t("refresh")}>
                  <RefreshCw className="w-3.5 h-3.5" />
                </button>
              </div>
            </div>

            <p className="text-xs text-text-muted max-w-3xl">{t("intro")}</p>

            {/* C5 — bandeau suggestions d'anticipation (proposed only) */}
            {suggestions.length > 0 && (
              <div className="bg-cyber-cyan/5 border border-cyber-cyan/20 rounded-lg px-4 py-3 space-y-2">
                <div className="flex items-center gap-2">
                  <Lightbulb className="w-4 h-4 text-cyber-cyan" />
                  <span className="text-sm font-medium text-text-primary">{t("suggestionsTitle")}</span>
                </div>
                <p className="text-[11px] text-text-muted">{t("suggestionsIntro")}</p>
                <div className="space-y-2">
                  {suggestions.map((s) => (
                    <div key={s.id} className="flex items-start justify-between gap-3 bg-bg-secondary border border-border-dim rounded px-3 py-2">
                      <div className="min-w-0 flex-1">
                        <p className="text-xs text-text-primary line-clamp-2">« {s.suggested_prompt} »</p>
                        <p className="text-[10px] text-text-muted mt-0.5">
                          <span className="text-cyber-cyan font-mono">
                            {describeCron(cadenceToCron(s.suggested_cadence) ?? s.suggested_cadence)}
                          </span>
                          {" · "}{t("suggestionOccurrences", { count: s.evidence.length })}
                        </p>
                      </div>
                      <div className="flex items-center gap-2 shrink-0">
                        <button
                          onClick={() => openCreateFromSuggestion(s)}
                          disabled={suggestionBusy === s.id}
                          className="text-[11px] px-2 py-1 rounded border border-cyber-cyan/30 bg-cyber-cyan/10 text-cyber-cyan hover:bg-cyber-cyan/20 disabled:opacity-40"
                        >
                          {t("suggestionCreate")}
                        </button>
                        <button
                          onClick={() => onSuggestionDismiss(s)}
                          disabled={suggestionBusy === s.id}
                          className="text-[11px] px-2 py-1 rounded border border-border-dim text-text-muted hover:text-text-secondary disabled:opacity-40 inline-flex items-center gap-1"
                        >
                          {suggestionBusy === s.id && <Loader2 className="w-3 h-3 animate-spin" />}
                          {t("suggestionDismiss")}
                        </button>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {error && (
              <div className="flex items-center gap-2 text-xs text-red-400 bg-red-500/10 border border-red-500/20 rounded px-3 py-2">
                <AlertCircle className="w-4 h-4" /> {error}
              </div>
            )}

            {loading ? (
              <div className="flex items-center justify-center py-12 text-text-muted">
                <Loader2 className="w-5 h-5 animate-spin mr-2" /> {t("loading")}
              </div>
            ) : tasks.length === 0 ? (
              <div className="text-center py-12 text-text-muted text-sm">{t("empty")}</div>
            ) : (
              <div className="space-y-2">
                {tasks.map((task) => (
                  <div
                    key={task.id}
                    className={`bg-bg-secondary border rounded-lg px-4 py-3 ${
                      task.enabled ? "border-border-dim" : "border-border-dim opacity-60"
                    }`}
                  >
                    <div className="flex items-start justify-between gap-3">
                      <div className="min-w-0 flex-1">
                        <div className="flex items-center gap-2 flex-wrap">
                          <span className="text-sm font-medium text-text-primary truncate">{task.name}</span>
                          <span className={`text-[9px] px-1.5 py-0.5 rounded border shrink-0 ${
                            task.enabled
                              ? "bg-emerald-500/10 border-emerald-500/20 text-emerald-400"
                              : "bg-bg-primary border-border-dim text-text-muted"
                          }`}>
                            {task.enabled ? t("badgeActive") : t("badgeDisabled")}
                          </span>
                          {/* Indicateur d'état d'exécution */}
                          {(() => {
                            const s = task.last_status;
                            const map = {
                              running: { cls: "bg-cyber-cyan/10 border-cyber-cyan/30 text-cyber-cyan animate-pulse", label: t("statusRunning"), dot: "●" },
                              success: { cls: "bg-emerald-500/10 border-emerald-500/20 text-emerald-400", label: t("statusSuccess"), dot: "✓" },
                              error:   { cls: "bg-red-500/10 border-red-500/30 text-red-400", label: t("statusError"), dot: "✕" },
                              // [SILENT] : la tâche a tourné sans rien à signaler — ce n'est PAS un échec.
                              silent:  { cls: "bg-bg-primary border-border-dim text-text-muted", label: t("statusSilent"), dot: "○" },
                              // Rendez-vous MANQUÉ, pas exécution : la tâche
                              // était due et la fenêtre de rattrapage l'a
                              // écartée. En orange, car rien ne sera rejoué.
                              missed:  { cls: "bg-amber-500/10 border-amber-500/30 text-amber-400", label: t("statusMissed"), dot: "⚠" },
                            } as const;
                            const fallback = { cls: "bg-bg-primary border-border-dim text-text-muted", label: t("statusNever"), dot: "○" };
                            // Défensif : un statut inconnu (ex. nouvelle valeur côté backend) NE DOIT PAS
                            // crasher le rendu de toute la page (cause du blocus /scheduled sur 'silent').
                            const m = (s ? map[s as keyof typeof map] : undefined) ?? fallback;
                            return (
                              <span className={`text-[9px] px-1.5 py-0.5 rounded border shrink-0 inline-flex items-center gap-1 ${m.cls}`}>
                                <span>{m.dot}</span>{m.label}
                              </span>
                            );
                          })()}
                          {task.as_mission && (
                            <span className="text-[9px] px-1.5 py-0.5 rounded border shrink-0 inline-flex items-center gap-1 bg-violet-500/10 border-violet-500/30 text-violet-300" title={t("badgeMissionHint")}>
                              <Target className="w-2.5 h-2.5" />{t("badgeMission")}
                            </span>
                          )}
                          <span className="text-[10px] text-cyber-cyan font-mono">{describeCron(task.cron_expression)}</span>
                          <span className="text-[10px] text-text-muted">· {task.channel}</span>
                        </div>
                        <p className="text-[11px] text-text-muted mt-1 line-clamp-2">{task.prompt}</p>
                        {task.last_run_at && (
                          <p className="text-[10px] text-text-muted mt-1">
                            {t("lastRun")} : {new Date(task.last_run_at).toLocaleString("fr-FR")}
                          </p>
                        )}
                        {/* Résultat / message d'erreur de la dernière exécution */}
                        {task.last_result && task.last_status !== "running" && (
                          <p className={`text-[10px] mt-1 line-clamp-2 ${
                            task.last_status === "error" ? "text-red-400" : "text-text-muted italic"
                          }`}>
                            {task.last_status === "error" ? "⚠ " : ""}{task.last_result}
                          </p>
                        )}
                      </div>

                      {/* Actions */}
                      <div className="flex items-center gap-1.5 shrink-0">
                        <button
                          onClick={() => onRun(task)}
                          disabled={busyId === task.id}
                          className="text-text-muted hover:text-cyber-cyan transition-colors disabled:opacity-40"
                          title={t("runNow")} aria-label={t("runNow")}
                        >
                          <Play className="w-3.5 h-3.5" />
                        </button>
                        <button
                          onClick={() => onToggle(task)}
                          disabled={busyId === task.id}
                          className={`transition-colors disabled:opacity-40 ${
                            task.enabled ? "text-emerald-400 hover:text-text-muted" : "text-text-muted hover:text-emerald-400"
                          }`}
                          title={task.enabled ? t("disable") : t("enable")}
                          aria-label={task.enabled ? t("disable") : t("enable")}
                        >
                          <Power className="w-3.5 h-3.5" />
                        </button>
                        <button
                          onClick={() => setConfirmId(task.id)}
                          disabled={busyId === task.id}
                          className="text-text-muted hover:text-red-400 transition-colors disabled:opacity-40"
                          title={t("delete")} aria-label={t("delete")}
                        >
                          <Trash2 className="w-3.5 h-3.5" />
                        </button>
                      </div>
                    </div>

                    {/* Confirm-delete inline sheet */}
                    {confirmId === task.id && (
                      <div className="mt-3 pt-3 border-t border-border-dim flex items-center justify-between gap-3">
                        <span className="text-[11px] text-red-400">{t("confirmBody", { name: task.name })}</span>
                        <div className="flex items-center gap-2 shrink-0">
                          <button
                            onClick={() => setConfirmId(null)}
                            className="text-[11px] px-2 py-1 rounded border border-border-dim text-text-muted hover:text-text-secondary"
                          >
                            <X className="w-3 h-3 inline" /> {t("cancel")}
                          </button>
                          <button
                            onClick={() => onDelete(task)}
                            disabled={busyId === task.id}
                            className="text-[11px] px-2 py-1 rounded border border-red-500/30 bg-red-500/10 text-red-400 hover:bg-red-500/20 disabled:opacity-40 inline-flex items-center gap-1"
                          >
                            {busyId === task.id && <Loader2 className="w-3 h-3 animate-spin" />}
                            {t("confirmDelete")}
                          </button>
                        </div>
                      </div>
                    )}
                  </div>
                ))}
              </div>
            )}

            {/* C5 — modal de création pré-remplie (l'utilisateur crée, jamais Ely) */}
            {prefill && (
              <div
                className="fixed inset-0 z-50 flex items-center justify-center bg-black/50"
                role="dialog" aria-modal="true"
                onKeyDown={(e) => { if (e.key === "Escape") setPrefill(null); }}
              >
                <div className="bg-bg-secondary border border-border-dim rounded-lg p-5 w-full max-w-lg mx-4 space-y-3">
                  <div className="flex items-center justify-between">
                    <h2 className="text-sm font-medium text-text-primary">{t("createModalTitle")}</h2>
                    <button onClick={() => setPrefill(null)} className="text-text-muted hover:text-text-secondary" aria-label={t("cancel")}>
                      <X className="w-4 h-4" />
                    </button>
                  </div>
                  <p className="text-[11px] text-text-muted">
                    {prefill.suggestionId !== null ? t("createModalIntro") : t("createModalIntroManual")}
                  </p>
                  <label className="block text-[11px] text-text-muted">
                    {t("createName")}
                    <input
                      value={prefill.name}
                      onChange={(e) => setPrefill({ ...prefill, name: e.target.value })}
                      className="mt-1 w-full bg-bg-primary border border-border-dim rounded px-2 py-1.5 text-xs text-text-primary"
                    />
                  </label>
                  <label className="block text-[11px] text-text-muted">
                    {t("createPrompt")}
                    <textarea
                      value={prefill.prompt}
                      onChange={(e) => setPrefill({ ...prefill, prompt: e.target.value })}
                      rows={3}
                      className="mt-1 w-full bg-bg-primary border border-border-dim rounded px-2 py-1.5 text-xs text-text-primary resize-y"
                    />
                  </label>
                  <label className="block text-[11px] text-text-muted">
                    {t("createCron")}
                    <input
                      value={prefill.cron}
                      onChange={(e) => setPrefill({ ...prefill, cron: e.target.value })}
                      className="mt-1 w-full bg-bg-primary border border-border-dim rounded px-2 py-1.5 text-xs font-mono text-text-primary"
                      placeholder="0 9 * * 1"
                    />
                    {describeCron(prefill.cron) !== prefill.cron && (
                      <span className="block mt-1 text-[10px] text-cyber-cyan">
                        {describeCron(prefill.cron)}
                      </span>
                    )}
                    {/* Les cinq champs nommés puis QUATRE exemples : « min heure
                        jour-du-mois mois jour-de-semaine » avec un seul exemple
                        ne disait pas comment écrire « tous les jours à 19h30 »
                        (Franck, 04/09). Un exemple par cas courant le dit. */}
                    <span className="block mt-1 text-[10px] text-text-muted font-mono">
                      {t("createCronFields")}
                    </span>
                    <span className="mt-1 grid grid-cols-1 sm:grid-cols-2 gap-x-4 gap-y-0.5 text-[10px] text-text-muted">
                      {([
                        ["createCronEgDaily", "30 12 * * *"],
                        ["createCronEgWeekdays", "0 8 * * 1-5"],
                        ["createCronEgMonday", "0 9 * * 1"],
                        ["createCronEgEveryTwoHours", "0 */2 * * *"],
                      ] as const).map(([cle, expr]) => (
                        <button
                          key={expr}
                          type="button"
                          onClick={() => setPrefill({ ...prefill, cron: expr })}
                          className="flex items-baseline justify-between gap-2 text-left hover:text-text-secondary"
                          title={t("createCronUseExample")}
                        >
                          <span>{t(cle)}</span>
                          <span className="font-mono text-cyber-cyan shrink-0">{expr}</span>
                        </button>
                      ))}
                    </span>
                  </label>
                  <label className="flex items-start gap-2 text-[11px] text-text-muted cursor-pointer">
                    <input
                      type="checkbox"
                      checked={prefill.asMission}
                      onChange={(e) => setPrefill({ ...prefill, asMission: e.target.checked })}
                      className="mt-0.5"
                    />
                    <span>
                      <span className="text-text-primary">{t("createAsMission")}</span>
                      <span className="block text-[10px] text-text-muted">{t("createAsMissionHint")}</span>
                    </span>
                  </label>
                  <div className="flex items-center justify-end gap-2 pt-1">
                    <button
                      onClick={() => setPrefill(null)}
                      className="text-[11px] px-3 py-1.5 rounded border border-border-dim text-text-muted hover:text-text-secondary"
                    >
                      {t("cancel")}
                    </button>
                    <button
                      onClick={onCreate}
                      disabled={creating || !prefill.name.trim() || !prefill.prompt.trim() || !prefill.cron.trim()}
                      className="text-[11px] px-3 py-1.5 rounded border border-cyber-cyan/30 bg-cyber-cyan/10 text-cyber-cyan hover:bg-cyber-cyan/20 disabled:opacity-40 inline-flex items-center gap-1.5"
                    >
                      {creating && <Loader2 className="w-3 h-3 animate-spin" />}
                      {creating ? t("createBusy") : t("createSubmit")}
                    </button>
                  </div>
                </div>
              </div>
            )}

            {/* Toast */}
            {toast && (
              <div className={`fixed bottom-6 right-6 text-xs px-4 py-2 rounded-lg border shadow-lg ${
                toast.kind === "ok"
                  ? "bg-emerald-500/10 border-emerald-500/30 text-emerald-300"
                  : "bg-red-500/10 border-red-500/30 text-red-300"
              }`}>
                {toast.msg}
              </div>
            )}
          </main>
        </div>
        </div>
      </div>
    </AuthGuard>
  );
}
