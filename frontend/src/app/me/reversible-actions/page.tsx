"use client";
/**
 * @project    ELY — Exactly Like You
 * @file       frontend/src/app/me/reversible-actions/page.tsx
 * @brief      Panneau d'annulation (Reversible Action Journal — J2b).
 *
 *             Liste les actions mutantes récentes que l'utilisateur peut encore
 *             annuler (suppression / renommage / déplacement Drive…) et expose
 *             un bouton « Annuler » par action. Tout passe par
 *             /api/me/reversible-actions (scopé à l'utilisateur courant) ; la
 *             logique fail-closed / vérification vit côté backend.
 *
 * @author     Franck OLLIVIER <contact@agent-ely.fr>
 * @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
 * @license    Elastic License 2.0
 */

import { useCallback, useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import {
  AlertCircle, CheckCircle, History, Loader2, RefreshCw, Undo2,
} from "lucide-react";

import { AuthGuard } from "@/components/layout/AuthGuard";
import { Header } from "@/components/layout/Header";
import { Sidebar } from "@/components/layout/Sidebar";
import { api, type ReversibleAction } from "@/lib/api";

function fmtDate(iso: string | null): string {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString("fr-FR", {
      day: "2-digit", month: "short", year: "2-digit",
      hour: "2-digit", minute: "2-digit",
    });
  } catch { return iso; }
}

export default function ReversibleActionsPage() {
  const t = useTranslations("reversibleActions");

  const [rows, setRows]       = useState<ReversibleAction[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError]     = useState<string | null>(null);
  const [busyId, setBusyId]   = useState<string | null>(null);
  const [flash, setFlash]     = useState<{ kind: "ok" | "warn" | "err"; text: string } | null>(null);

  const showFlash = (kind: "ok" | "warn" | "err", text: string) => {
    setFlash({ kind, text });
    setTimeout(() => setFlash(null), 5000);
  };

  const fetchRows = useCallback(async () => {
    setLoading(true); setError(null);
    try {
      setRows(await api.reversibleActions());
    } catch (e) {
      setError(e instanceof Error ? e.message : t("errorLoad"));
    } finally {
      setLoading(false);
    }
  }, [t]);

  useEffect(() => { fetchRows(); }, [fetchRows]);

  const undo = async (row: ReversibleAction) => {
    if (busyId) return;
    setBusyId(row.id);
    try {
      const res = await api.undoReversibleAction(row.id);
      // Quoi qu'il arrive l'action n'est plus annulable → on la retire.
      setRows((cur) => cur.filter((r) => r.id !== row.id));
      if (res.verified === false) showFlash("warn", t("flashUnverified"));
      else showFlash("ok", t("flashUndone"));
    } catch (e) {
      showFlash("err", e instanceof Error ? e.message : t("actionError"));
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
          <main
            className="flex-1 overflow-y-auto p-6 space-y-4"
            style={{ background: "var(--bg-app)" }}
          >
            {/* Header */}
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div className="flex items-center gap-3">
                <History className="w-5 h-5 text-cyber-cyan" />
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
              {t("note")}
            </p>

            {/* Flash */}
            {flash && (
              <div className={`flex items-center gap-2 px-3 py-2 rounded border text-xs ${
                flash.kind === "ok"
                  ? "bg-emerald-900/40 border-emerald-500/30 text-emerald-300"
                  : flash.kind === "warn"
                    ? "bg-amber-900/40 border-amber-500/30 text-amber-300"
                    : "bg-red-900/40 border-red-500/30 text-red-300"
              }`}>
                {flash.kind === "err" ? <AlertCircle className="w-3.5 h-3.5" /> : <CheckCircle className="w-3.5 h-3.5" />}
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
                <Undo2 className="w-8 h-8 text-text-muted mx-auto mb-3" />
                <p className="text-sm text-text-secondary">{t("empty")}</p>
              </div>
            )}

            {/* List */}
            {!loading && !error && rows.length > 0 && (
              <section className="bg-bg-secondary border border-border-dim rounded-lg overflow-hidden">
                <header className="flex items-center gap-2 px-4 py-3 border-b border-border-dim">
                  <span className="px-2 py-0.5 text-[10px] font-mono rounded border bg-cyber-cyan/10 text-cyber-cyan border-cyber-cyan/30">
                    {t("title")}
                  </span>
                  <span className="ml-auto text-[10px] text-text-muted">{rows.length}</span>
                </header>
                <ul className="divide-y divide-border-dim/50">
                  {rows.map((r) => (
                    <li key={r.id} className="px-4 py-3">
                      <div className="flex items-start gap-3">
                        <div className="flex-1 min-w-0">
                          <p className="text-sm text-text-primary font-mono">{r.capability_id}</p>
                          <div className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-0.5 text-[10px] text-text-muted">
                            <span>{t("createdLabel", { date: fmtDate(r.created_at) })}</span>
                            <span>{t("expiresLabel", { date: fmtDate(r.expires_at) })}</span>
                          </div>
                        </div>
                        <div className="shrink-0">
                          <button
                            onClick={() => undo(r)}
                            disabled={busyId === r.id}
                            className="flex items-center gap-1 px-2.5 py-1 text-[11px] rounded border border-cyber-cyan/30 text-cyber-cyan hover:bg-cyber-cyan/10 transition-colors disabled:opacity-50"
                            title={t("undo")}
                          >
                            {busyId === r.id
                              ? <Loader2 className="w-3 h-3 animate-spin" />
                              : <Undo2 className="w-3 h-3" />}
                            {busyId === r.id ? t("undoing") : t("undo")}
                          </button>
                        </div>
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
    </AuthGuard>
  );
}
