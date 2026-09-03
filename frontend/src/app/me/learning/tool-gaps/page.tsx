"use client";
/**
 * @project    ELY — Exactly Like You
 * @file       frontend/src/app/me/learning/tool-gaps/page.tsx
 * @brief      Admin HITL review of capability gaps (find_tool Phase 2).
 *
 *             When the model calls `find_tool` and the semantic+lexical search
 *             returns no relevant tool, `failure_capture.record_tool_absent`
 *             persists the capability as a FailureCase. This page surfaces
 *             those gaps so the admin can either:
 *               - generate a python_tool via /admin/learning/tool-creator/run
 *                 (escalates the gap into the auto-dev pipeline) → the
 *                 resulting candidate lands on /me/learning/candidates,
 *               - or mark the gap processed (out of scope, duplicate…).
 *
 *             Lives under /me/* (not /admin/*) because next.config rewrites
 *             /admin/* to the backend (gotcha doc'd on the candidates page).
 *
 * @author     Franck OLLIVIER <contact@agent-ely.fr>
 * @copyright  Copyright (c) 2025-2026 Franck OLLIVIER
 * @license    MIT
 *            https://opensource.org/licenses/MIT
 */

import { useCallback, useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import {
  AlertCircle, CheckCircle, CheckCircle2, Loader2, RefreshCw,
  Search, ShieldCheck, Sparkles, X,
} from "lucide-react";

import { AdminGuard } from "@/components/layout/AuthGuard";
import { Header } from "@/components/layout/Header";
import { Sidebar } from "@/components/layout/Sidebar";
import { api, type ToolGap } from "@/lib/api";

const FILTERS = ["open", "all"] as const;
type Filter = (typeof FILTERS)[number];

function fmtDate(iso: string | null): string {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString("fr-FR", {
      day: "2-digit", month: "short", year: "2-digit",
      hour: "2-digit", minute: "2-digit",
    });
  } catch { return iso; }
}

export default function ToolGapsPage() {
  const t = useTranslations("toolGaps");

  const [filter, setFilter]   = useState<Filter>("open");
  const [rows, setRows]       = useState<ToolGap[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError]     = useState<string | null>(null);
  const [busyId, setBusyId]   = useState<number | null>(null);
  const [flash, setFlash]     = useState<{ kind: "ok" | "err"; text: string } | null>(null);

  // Confirmation modal for "Generate tool" (it calls a paid tier-S LLM)
  const [confirmGap, setConfirmGap] = useState<ToolGap | null>(null);

  const showFlash = (kind: "ok" | "err", text: string) => {
    setFlash({ kind, text });
    setTimeout(() => setFlash(null), 4500);
  };

  const fetchRows = useCallback(async () => {
    setLoading(true); setError(null);
    try {
      const data = await api.adminLearningToolGaps(filter);
      setRows(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : t("errorLoad"));
    } finally {
      setLoading(false);
    }
  }, [filter, t]);

  useEffect(() => { fetchRows(); }, [fetchRows]);

  const markProcessed = async (gap: ToolGap) => {
    if (busyId) return;
    setBusyId(gap.id);
    try {
      await api.adminLearningToolGapMarkProcessed(gap.id);
      // Open-list: drop the row; All-list: refetch to show new processed_at.
      if (filter === "open") {
        setRows((cur) => cur.filter((r) => r.id !== gap.id));
      } else {
        await fetchRows();
      }
      showFlash("ok", t("flash_marked", { cap: gap.capability.slice(0, 60) }));
    } catch (e) {
      showFlash("err", e instanceof Error ? e.message : t("actionError"));
    } finally {
      setBusyId(null);
    }
  };

  const generateTool = async (gap: ToolGap) => {
    setConfirmGap(null);
    if (busyId) return;
    setBusyId(gap.id);
    try {
      const result = await api.adminLearningToolCreatorRun({
        task_description: gap.capability,
        user_id: gap.user_id,
      });
      if (result.status === "created" && result.learned_skill_id) {
        // Link the gap to the new candidate and mark it processed in one shot.
        await api.adminLearningToolGapMarkProcessed(gap.id, result.learned_skill_id);
        showFlash("ok", t("flash_generated", { name: result.tool_name ?? "tool" }));
        if (filter === "open") setRows((cur) => cur.filter((r) => r.id !== gap.id));
        else await fetchRows();
      } else {
        showFlash("err", t("flash_generation_failed", { status: result.status }));
      }
    } catch (e) {
      showFlash("err", e instanceof Error ? e.message : t("actionError"));
    } finally {
      setBusyId(null);
    }
  };

  return (
    <AdminGuard>
      <div className="flex h-screen overflow-hidden">
        <Sidebar />
        <div className="flex flex-col flex-1 min-w-0 overflow-hidden">
        <Header />
        <div className="flex flex-1 overflow-hidden">
          <main
            className="flex-1 overflow-y-auto p-6 space-y-4"
            style={{ background: "var(--bg-app)" }}
          >
            {/* Header */}
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div className="flex items-center gap-3">
                <Search className="w-5 h-5 text-cyber-cyan" />
                <h1 className="text-lg font-medium text-text-primary">{t("title")}</h1>
                <span className="text-[11px] text-text-muted">{t("subtitle")}</span>
              </div>
              <button
                onClick={fetchRows}
                disabled={loading}
                className="p-1.5 text-text-muted hover:text-cyber-cyan hover:bg-cyber-cyan/10 rounded transition-colors disabled:opacity-50"
                title={t("refreshTooltip")}
              >
                {loading ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <RefreshCw className="w-3.5 h-3.5" />}
              </button>
            </div>

            {/* Note */}
            <p className="text-[11px] text-text-muted bg-bg-secondary border border-border-dim rounded px-3 py-2">
              {t("adminNote")}
            </p>

            {/* Filter chips */}
            <div className="flex flex-wrap items-center gap-1.5">
              {FILTERS.map((f) => (
                <button
                  key={f}
                  onClick={() => setFilter(f)}
                  className={`px-2.5 py-1 text-[11px] font-mono rounded border transition-colors ${
                    filter === f
                      ? "bg-cyber-cyan/10 text-cyber-cyan border-cyber-cyan/30"
                      : "bg-bg-primary text-text-muted border-border-dim hover:text-text-secondary"
                  }`}
                >
                  {t(`filter_${f}`)}
                </button>
              ))}
            </div>

            {/* Flash */}
            {flash && (
              <div className={`flex items-center gap-2 px-3 py-2 rounded border text-xs ${
                flash.kind === "ok"
                  ? "bg-emerald-900/40 border-emerald-500/30 text-emerald-300"
                  : "bg-red-900/40 border-red-500/30 text-red-300"
              }`}>
                {flash.kind === "ok" ? <CheckCircle className="w-3.5 h-3.5" /> : <AlertCircle className="w-3.5 h-3.5" />}
                {flash.text}
              </div>
            )}

            {/* Error */}
            {error && (
              <div className="flex items-center gap-2 text-xs text-red-400 bg-red-500/10 border border-red-500/20 rounded px-3 py-2">
                <AlertCircle className="w-4 h-4" />
                {error}
              </div>
            )}

            {/* Loading */}
            {loading && !error && (
              <div className="flex items-center justify-center py-12 text-text-muted">
                <Loader2 className="w-5 h-5 animate-spin mr-2" />
                {t("loading")}
              </div>
            )}

            {/* Empty */}
            {!loading && !error && rows.length === 0 && (
              <div className="bg-bg-secondary border border-border-dim rounded-lg p-8 text-center">
                <Sparkles className="w-8 h-8 text-text-muted mx-auto mb-3" />
                <p className="text-sm text-text-secondary">
                  {filter === "open" ? t("emptyOpen") : t("emptyAll")}
                </p>
              </div>
            )}

            {/* List */}
            {!loading && !error && rows.length > 0 && (
              <section className="bg-bg-secondary border border-border-dim rounded-lg overflow-hidden">
                <header className="flex items-center gap-2 px-4 py-3 border-b border-border-dim">
                  <span className="px-2 py-0.5 text-[10px] font-mono rounded border bg-cyber-cyan/10 text-cyber-cyan border-cyber-cyan/30">
                    {t(`filter_${filter}`)}
                  </span>
                  <span className="ml-auto text-[10px] text-text-muted">{rows.length}</span>
                </header>
                <ul className="divide-y divide-border-dim/50">
                  {rows.map((g) => (
                    <li key={g.id} className="px-4 py-3">
                      <div className="flex items-start gap-3">
                        <div className="flex-1 min-w-0">
                          {/* Capability */}
                          <p className="text-sm text-text-primary">
                            {g.capability}
                          </p>
                          {/* Metadata row */}
                          <div className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-0.5 text-[10px] text-text-muted">
                            <span>{t("createdLabel", { date: fmtDate(g.created_at) })}</span>
                            <span className="font-mono">
                              {t("userLabel", { id: g.user_id.slice(0, 8) })}
                            </span>
                            {g.processed_at && (
                              <span className="text-emerald-400">
                                ✓ {t("processedAt", { date: fmtDate(g.processed_at) })}
                              </span>
                            )}
                            {g.learned_skill_id && (
                              <span className="font-mono text-cyber-cyan">
                                → skill {g.learned_skill_id.slice(0, 8)}
                              </span>
                            )}
                          </div>
                        </div>
                        {/* Actions — only on open gaps */}
                        {g.processed_at === null && (
                          <div className="flex items-center gap-1.5 shrink-0">
                            <button
                              onClick={() => setConfirmGap(g)}
                              disabled={busyId === g.id}
                              className="flex items-center gap-1 px-2 py-1 text-[11px] rounded border border-emerald-500/30 text-emerald-300 hover:bg-emerald-500/10 transition-colors disabled:opacity-50"
                              title={t("generateHint")}
                            >
                              {busyId === g.id
                                ? <Loader2 className="w-3 h-3 animate-spin" />
                                : <CheckCircle2 className="w-3 h-3" />}
                              {t("generate")}
                            </button>
                            <button
                              onClick={() => markProcessed(g)}
                              disabled={busyId === g.id}
                              className="flex items-center gap-1 px-2 py-1 text-[11px] rounded border border-border-dim text-text-muted hover:text-amber-300 hover:border-amber-500/30 transition-colors disabled:opacity-50"
                              title={t("markProcessedHint")}
                            >
                              {busyId === g.id
                                ? <Loader2 className="w-3 h-3 animate-spin" />
                                : <X className="w-3 h-3" />}
                              {t("markProcessed")}
                            </button>
                          </div>
                        )}
                      </div>
                    </li>
                  ))}
                </ul>
              </section>
            )}
          </main>
        </div>
        </div>
      </div>

      {/* Confirmation modal for "Generate tool" — paid LLM call. */}
      {confirmGap && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
          <div className="bg-bg-secondary border border-border-dim rounded-lg max-w-md w-full mx-4 p-5 space-y-3">
            <div className="flex items-center gap-2">
              <ShieldCheck className="w-5 h-5 text-cyber-cyan" />
              <h2 className="text-sm font-medium text-text-primary">
                {t("confirmTitle")}
              </h2>
            </div>
            <p className="text-xs text-text-secondary">{t("confirmBody")}</p>
            <p className="text-xs text-text-muted bg-bg-primary border border-border-dim rounded p-2 font-mono">
              {confirmGap.capability}
            </p>
            <div className="flex items-center gap-2 justify-end">
              <button
                onClick={() => setConfirmGap(null)}
                className="px-3 py-1.5 text-[11px] rounded border border-border-dim text-text-muted hover:text-text-secondary"
              >
                {t("cancel")}
              </button>
              <button
                onClick={() => generateTool(confirmGap)}
                className="px-3 py-1.5 text-[11px] rounded border border-emerald-500/30 text-emerald-300 hover:bg-emerald-500/10 flex items-center gap-1"
              >
                <CheckCircle2 className="w-3 h-3" />
                {t("confirmGenerate")}
              </button>
            </div>
          </div>
        </div>
      )}
    </AdminGuard>
  );
}
