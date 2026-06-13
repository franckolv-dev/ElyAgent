"use client";
/**
 * @project    ELY — Exactly Like You
 * @file       frontend/src/app/scheduled/page.tsx
 * @brief      Tâches planifiées — liste + suppression RÉELLE + activer/
 *             désactiver + exécuter maintenant. Comble le manque d'UI qui
 *             rendait les tâches cron de l'agent invisibles (bug 13/06).
 *
 * @author     Franck OLLIVIER <contact@agent-ely.fr>
 * @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
 * @license    Elastic License 2.0
 */

import { useCallback, useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { AuthGuard } from "@/components/layout/AuthGuard";
import { Sidebar } from "@/components/layout/Sidebar";
import { Header } from "@/components/layout/Header";
import {
  Clock, Loader2, AlertCircle, Trash2, Play, Power, RefreshCw, X,
} from "lucide-react";
import { schedulerApi, describeCron, type ScheduledTask } from "@/lib/scheduler";

export default function ScheduledTasksPage() {
  const t = useTranslations("scheduled");
  const [tasks, setTasks]     = useState<ScheduledTask[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError]     = useState<string | null>(null);
  const [toast, setToast]     = useState<{ kind: "ok" | "err"; msg: string } | null>(null);
  const [confirmId, setConfirmId] = useState<string | null>(null);
  const [busyId, setBusyId]   = useState<string | null>(null);

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
      <div className="flex flex-col h-screen overflow-hidden">
        <Header />
        <div className="flex flex-1 overflow-hidden">
          <Sidebar />
          <main className="flex-1 overflow-y-auto p-6 space-y-4" style={{ background: "var(--bg-app)" }}>

            {/* Header */}
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-3">
                <Clock className="w-5 h-5 text-cyber-cyan" />
                <h1 className="text-lg font-medium text-text-primary">{t("title")}</h1>
                <span className="text-[11px] text-text-muted">({tasks.length})</span>
              </div>
              <button onClick={() => { setLoading(true); fetchAll(); }} className="btn" title={t("refresh")}>
                <RefreshCw className="w-3.5 h-3.5" />
              </button>
            </div>

            <p className="text-xs text-text-muted max-w-3xl">{t("intro")}</p>

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
                          <span className="text-[10px] text-cyber-cyan font-mono">{describeCron(task.cron_expression)}</span>
                          <span className="text-[10px] text-text-muted">· {task.channel}</span>
                        </div>
                        <p className="text-[11px] text-text-muted mt-1 line-clamp-2">{task.prompt}</p>
                        {task.last_run_at && (
                          <p className="text-[10px] text-text-muted mt-1">
                            {t("lastRun")} : {new Date(task.last_run_at).toLocaleString("fr-FR")}
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
    </AuthGuard>
  );
}
