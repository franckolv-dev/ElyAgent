"use client";
/**
 * @project    ELY — Exactly Like You
 * @file       frontend/src/app/me/learning/incidents/page.tsx
 * @brief      Boucle d'auto-diagnostic J4 — page admin « Incidents & propositions ».
 *
 *             Maillon 3 de la remontée : liste les exécutions douteuses/échouées
 *             diagnostiquées (cause + catégorie), et laisse l'admin trancher
 *             (valider / rejeter) ou agir selon la voie A/B/C/D :
 *               - voie B (gap_tool/binding) → générer un outil (auto-dev),
 *               - voie C (config_tier/prompt) → patch config/prompt (J5, différé),
 *               - voie D (code_core) → ticket humain,
 *               - voie A → rien à corriger.
 *
 *             Réutilise le gabarit de /me/learning/tool-gaps. Sous /me/* car
 *             next.config réécrit /admin/* vers le backend.
 *
 * @author     Franck OLLIVIER <contact@agent-ely.fr>
 * @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
 * @license    Elastic License 2.0
 */

import { useCallback, useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import {
  AlertCircle, AlertTriangle, CheckCircle, CheckCircle2, FilePen, Loader2,
  RefreshCw, Sparkles, Stethoscope, ThumbsDown, Undo2, Wrench,
} from "lucide-react";

import { AdminGuard } from "@/components/layout/AuthGuard";
import { Header } from "@/components/layout/Header";
import { Sidebar } from "@/components/layout/Sidebar";
import { api, ApiError, type Incident } from "@/lib/api";

const FILTERS = ["open", "all"] as const;
type Filter = (typeof FILTERS)[number];

// Catégorie de cause → voie de traitement (frontière A/B/C/D de la design note).
const VOIE: Record<string, "A" | "B" | "C" | "D"> = {
  gap_tool: "B",
  binding: "B",
  config_tier: "C",
  prompt: "C",
  code_core: "D",
  user_interaction: "A",
  unknown: "A",
};

function fmtDate(iso: string | null): string {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString("fr-FR", {
      day: "2-digit", month: "short", year: "2-digit",
      hour: "2-digit", minute: "2-digit",
    });
  } catch { return iso; }
}

export default function IncidentsPage() {
  const t = useTranslations("incidents");

  const [filter, setFilter]   = useState<Filter>("open");
  const [rows, setRows]       = useState<Incident[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError]     = useState<string | null>(null);
  const [busyId, setBusyId]   = useState<number | null>(null);
  const [flash, setFlash]     = useState<{ kind: "ok" | "err"; text: string } | null>(null);
  const [confirmGen, setConfirmGen] = useState<Incident | null>(null);

  const showFlash = (kind: "ok" | "err", text: string) => {
    setFlash({ kind, text });
    setTimeout(() => setFlash(null), 4500);
  };

  const fetchRows = useCallback(async () => {
    setLoading(true); setError(null);
    try {
      setRows(await api.adminLearningIncidents(filter));
    } catch (e) {
      setError(e instanceof Error ? e.message : t("errorLoad"));
    } finally {
      setLoading(false);
    }
  }, [filter, t]);

  useEffect(() => { fetchRows(); }, [fetchRows]);

  const dropOrRefetch = async (id: number) => {
    if (filter === "open") setRows((cur) => cur.filter((r) => r.id !== id));
    else await fetchRows();
  };

  const resolve = async (inc: Incident, status: "validated" | "rejected") => {
    if (busyId) return;
    setBusyId(inc.id);
    try {
      await api.adminLearningIncidentResolve(inc.id, status);
      await dropOrRefetch(inc.id);
      showFlash("ok", t(status === "validated" ? "flash_validated" : "flash_rejected"));
    } catch (e) {
      showFlash("err", e instanceof Error ? e.message : t("actionError"));
    } finally {
      setBusyId(null);
    }
  };

  const generateTool = async (inc: Incident) => {
    setConfirmGen(null);
    if (busyId) return;
    setBusyId(inc.id);
    try {
      const result = await api.adminLearningToolCreatorRun({
        task_description: inc.hypothesis,
        user_id: inc.user_id,
      });
      if (result.status === "created") {
        await api.adminLearningIncidentResolve(
          inc.id, "actioned", `tool:${result.tool_name ?? "?"}`,
        );
        await dropOrRefetch(inc.id);
        showFlash("ok", t("flash_generated", { name: result.tool_name ?? "tool" }));
      } else if (result.status === "exists") {
        // `exists` N'EST PAS UN ÉCHEC — c'est la confirmation de l'hypothèse.
        // Le backend refuse de dépenser un appel tier-S parce qu'un outil
        // couvre déjà la capacité, et il le NOMME. Or l'incident disait
        // « l'outil existe mais n'a pas été lié à ce tour ». La réponse lui
        // donne raison.
        //
        // L'affichage rangeait ça en « Génération échouée (status: exists) »
        // et laissait l'incident ouvert : le seul retour possible était de
        // recliquer indéfiniment. (21/08)
        //
        // ⚠️ `validated` et pas `actioned` : l'hypothèse est confirmée, mais
        // RIEN n'est réparé — le trou de binding reste entier. Dire
        // « actioned » ferait croire à un correctif qui n'existe pas.
        await api.adminLearningIncidentResolve(
          inc.id, "validated", `outil existant : ${result.tool_name ?? "?"}`,
        );
        await dropOrRefetch(inc.id);
        showFlash("ok", t("flash_tool_exists", { name: result.tool_name ?? "?" }));
      } else {
        showFlash("err", t("flash_generation_failed", { status: result.status }));
      }
    } catch (e) {
      showFlash("err", e instanceof Error ? e.message : t("actionError"));
    } finally {
      setBusyId(null);
    }
  };

  // ── J5 — correctifs validables (voie C) ──
  const proposePatch = async (inc: Incident) => {
    if (busyId) return;
    setBusyId(inc.id);
    try {
      const patch = await api.adminLearningProposePatch(inc.id);
      // MAJ locale (pas de refetch) : le diff s'affiche et la carte RESTE en
      // place — fetchRows() re-triait la liste et la déplaçait hors de vue.
      setRows((cur) => cur.map((r) => (r.id === inc.id ? { ...r, patch } : r)));
      showFlash("ok", t("flash_patch_proposed"));
    } catch (e) {
      // 410 — la tâche planifiée visée n'existe plus. Le backend a classé
      // l'incident « obsolete » ; la carte doit partir avec lui. Sans ça,
      // l'incident restait à l'écran et chaque clic rejouait la même erreur :
      // aucun chemin ne le faisait sortir de la liste (21/08).
      if (e instanceof ApiError && e.status === 410) {
        await dropOrRefetch(inc.id);
        showFlash("ok", t("flash_target_gone"));
      } else {
        showFlash("err", e instanceof Error ? e.message : t("actionError"));
      }
    } finally {
      setBusyId(null);
    }
  };

  const applyPatch = async (inc: Incident, patchId: number) => {
    if (busyId) return;
    setBusyId(inc.id);
    try {
      await api.adminLearningApplyPatch(patchId);
      await dropOrRefetch(inc.id);    // l'incident passe « actioned »
      showFlash("ok", t("flash_patch_applied"));
    } catch (e) {
      // Même impasse un clic plus tard : correctif proposé, tâche supprimée
      // entre-temps. Le correctif est caduc, l'incident classé.
      if (e instanceof ApiError && e.status === 410) {
        await dropOrRefetch(inc.id);
        showFlash("ok", t("flash_target_gone"));
      } else {
        showFlash("err", e instanceof Error ? e.message : t("actionError"));
      }
    } finally {
      setBusyId(null);
    }
  };

  const revertPatch = async (inc: Incident, patchId: number) => {
    if (busyId) return;
    setBusyId(inc.id);
    try {
      await api.adminLearningRevertPatch(patchId);
      await fetchRows();
      showFlash("ok", t("flash_patch_reverted"));
    } catch (e) {
      showFlash("err", e instanceof Error ? e.message : t("actionError"));
    } finally {
      setBusyId(null);
    }
  };

  const rejectPatch = async (inc: Incident, patchId: number) => {
    if (busyId) return;
    setBusyId(inc.id);
    try {
      await api.adminLearningRejectPatch(patchId);
      await fetchRows();
      showFlash("ok", t("flash_patch_rejected"));
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
                <Stethoscope className="w-5 h-5 text-cyber-cyan" />
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

            {error && (
              <div className="flex items-center gap-2 text-xs text-red-400 bg-red-500/10 border border-red-500/20 rounded px-3 py-2">
                <AlertCircle className="w-4 h-4" />
                {error}
              </div>
            )}

            {loading && !error && (
              <div className="flex items-center justify-center py-12 text-text-muted">
                <Loader2 className="w-5 h-5 animate-spin mr-2" />
                {t("loading")}
              </div>
            )}

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
                  {rows.map((inc) => {
                    const voie = VOIE[inc.category] ?? "A";
                    const isOpen = inc.status === "open";
                    return (
                      <li key={inc.id} className="px-4 py-3">
                        <div className="flex items-start gap-3">
                          <div className="flex-1 min-w-0 space-y-1.5">
                            {/* Badges row */}
                            <div className="flex flex-wrap items-center gap-1.5">
                              <span className={`px-1.5 py-0.5 text-[10px] font-mono rounded border ${
                                inc.outcome === "failed"
                                  ? "bg-red-500/10 text-red-300 border-red-500/30"
                                  : "bg-amber-500/10 text-amber-300 border-amber-500/30"
                              }`}>
                                {t(`outcome_${inc.outcome}`)}
                              </span>
                              <span className="px-1.5 py-0.5 text-[10px] font-mono rounded border bg-bg-primary text-text-secondary border-border-dim">
                                {t(`category_${inc.category}`)}
                              </span>
                              <span className={`px-1.5 py-0.5 text-[10px] font-mono rounded border ${
                                inc.confidence === "high"
                                  ? "bg-red-500/10 text-red-300 border-red-500/30"
                                  : inc.confidence === "low"
                                  ? "bg-bg-primary text-text-muted border-border-dim"
                                  : "bg-amber-500/10 text-amber-300 border-amber-500/30"
                              }`}>
                                {t("confidenceLabel", { level: t(`confidence_${inc.confidence}`) })}
                              </span>
                              <span className="px-1.5 py-0.5 text-[10px] font-mono rounded border bg-cyber-cyan/10 text-cyber-cyan border-cyber-cyan/30">
                                {t(`voie_${voie}`)}
                              </span>
                              {!isOpen && (
                                <span className={`px-1.5 py-0.5 text-[10px] font-mono rounded border ${
                                  // « fusionné » et « sans objet » ne sont pas
                                  // des succès : l'incident n'a rien produit,
                                  // il a été rangé. Le vert est réservé à ce
                                  // qui a été tranché ou traité.
                                  inc.status === "merged" || inc.status === "obsolete"
                                    ? "bg-bg-primary text-text-muted border-border-dim"
                                    : "bg-emerald-500/10 text-emerald-300 border-emerald-500/30"
                                }`}>
                                  {t(`status_${inc.status}`)}
                                </span>
                              )}
                            </div>
                            {/* Hypothesis */}
                            <p className="text-sm text-text-primary">{inc.hypothesis}</p>
                            {/* Signals chips */}
                            {inc.signals.length > 0 && (
                              <div className="flex flex-wrap gap-1">
                                {inc.signals.map((s) => (
                                  <span key={s} className="px-1.5 py-0.5 text-[10px] font-mono rounded bg-bg-primary text-text-muted border border-border-dim">
                                    {s}
                                  </span>
                                ))}
                              </div>
                            )}
                            {/* Metadata */}
                            <div className="flex flex-wrap items-center gap-x-3 gap-y-0.5 text-[10px] text-text-muted">
                              <span>{t("createdLabel", { date: fmtDate(inc.created_at) })}</span>
                              {(inc.occurrences ?? 1) > 1 && (
                                <span className="text-amber-300/90">
                                  {t("seenTimes", {
                                    count: inc.occurrences,
                                    date: fmtDate(inc.last_seen_at ?? inc.created_at),
                                  })}
                                </span>
                              )}
                              <span className="font-mono">{inc.source}{inc.tier_llm ? ` · tier ${inc.tier_llm}` : ""}</span>
                              {inc.model_used && <span className="font-mono">{inc.model_used}</span>}
                              {inc.channel && <span className="font-mono">{inc.channel}</span>}
                              <span className="font-mono opacity-60">{inc.critic_model ?? "—"}</span>
                            </div>
                            {/* J5 — correctif proposé (diff + actions) */}
                            {inc.patch && (
                              <div className="mt-2 rounded border border-cyber-cyan/20 bg-cyber-cyan/5 p-2 space-y-2">
                                <div className="flex items-center gap-2">
                                  <FilePen className="w-3 h-3 text-cyber-cyan" />
                                  <span className="text-[11px] text-text-secondary">{t("patchTitle")}</span>
                                  <span className={`px-1.5 py-0.5 text-[10px] font-mono rounded border ${
                                    inc.patch.status === "applied"
                                      ? "bg-emerald-500/10 text-emerald-300 border-emerald-500/30"
                                      : inc.patch.status === "proposed"
                                      ? "bg-amber-500/10 text-amber-300 border-amber-500/30"
                                      : "bg-bg-primary text-text-muted border-border-dim"
                                  }`}>
                                    {t(`patch_status_${inc.patch.status}`)}
                                  </span>
                                </div>
                                {inc.patch.rationale && (
                                  <p className="text-[11px] text-text-secondary">{inc.patch.rationale}</p>
                                )}
                                <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                                  <div>
                                    <div className="text-[10px] text-text-muted mb-0.5">{t("patchBefore")}</div>
                                    <pre className="text-[10px] font-mono whitespace-pre-wrap break-words max-h-32 overflow-y-auto rounded bg-red-500/5 border border-red-500/20 text-text-secondary p-1.5">{inc.patch.old_value ?? "—"}</pre>
                                  </div>
                                  <div>
                                    <div className="text-[10px] text-text-muted mb-0.5">{t("patchAfter")}</div>
                                    <pre className="text-[10px] font-mono whitespace-pre-wrap break-words max-h-32 overflow-y-auto rounded bg-emerald-500/5 border border-emerald-500/20 text-text-secondary p-1.5">{inc.patch.new_value}</pre>
                                  </div>
                                </div>
                                {/* Patch actions */}
                                <div className="flex flex-wrap items-center gap-1.5">
                                  {inc.patch.status === "proposed" && (
                                    <>
                                      <button
                                        onClick={() => applyPatch(inc, inc.patch!.id)}
                                        disabled={busyId === inc.id}
                                        className="flex items-center gap-1 px-2 py-1 text-[11px] rounded border border-emerald-500/30 text-emerald-300 hover:bg-emerald-500/10 transition-colors disabled:opacity-50"
                                        title={t("applyHint")}
                                      >
                                        {busyId === inc.id ? <Loader2 className="w-3 h-3 animate-spin" /> : <CheckCircle2 className="w-3 h-3" />}
                                        {t("apply")}
                                      </button>
                                      <button
                                        onClick={() => rejectPatch(inc, inc.patch!.id)}
                                        disabled={busyId === inc.id}
                                        className="flex items-center gap-1 px-2 py-1 text-[11px] rounded border border-border-dim text-text-muted hover:text-red-300 hover:border-red-500/30 transition-colors disabled:opacity-50"
                                        title={t("rejectPatchHint")}
                                      >
                                        {busyId === inc.id ? <Loader2 className="w-3 h-3 animate-spin" /> : <ThumbsDown className="w-3 h-3" />}
                                        {t("rejectPatch")}
                                      </button>
                                    </>
                                  )}
                                  {inc.patch.status === "applied" && (
                                    <button
                                      onClick={() => revertPatch(inc, inc.patch!.id)}
                                      disabled={busyId === inc.id}
                                      className="flex items-center gap-1 px-2 py-1 text-[11px] rounded border border-amber-500/30 text-amber-300 hover:bg-amber-500/10 transition-colors disabled:opacity-50"
                                      title={t("revertHint")}
                                    >
                                      {busyId === inc.id ? <Loader2 className="w-3 h-3 animate-spin" /> : <Undo2 className="w-3 h-3" />}
                                      {t("revert")}
                                    </button>
                                  )}
                                </div>
                              </div>
                            )}
                          </div>
                          {/* Actions — only while open */}
                          {isOpen && (
                            <div className="flex flex-col items-stretch gap-1.5 shrink-0">
                              {voie === "B" && (
                                <button
                                  onClick={() => setConfirmGen(inc)}
                                  disabled={busyId === inc.id}
                                  className="flex items-center gap-1 px-2 py-1 text-[11px] rounded border border-cyber-cyan/30 text-cyber-cyan hover:bg-cyber-cyan/10 transition-colors disabled:opacity-50"
                                  title={t("generateHint")}
                                >
                                  {busyId === inc.id ? <Loader2 className="w-3 h-3 animate-spin" /> : <Wrench className="w-3 h-3" />}
                                  {t("generate")}
                                </button>
                              )}
                              {voie === "C" && inc.source === "scheduled" &&
                                (!inc.patch || ["rejected", "reverted"].includes(inc.patch.status)) && (
                                <button
                                  onClick={() => proposePatch(inc)}
                                  disabled={busyId === inc.id}
                                  className="flex items-center gap-1 px-2 py-1 text-[11px] rounded border border-cyber-cyan/30 text-cyber-cyan hover:bg-cyber-cyan/10 transition-colors disabled:opacity-50"
                                  title={t("proposePatchHint")}
                                >
                                  {busyId === inc.id ? <Loader2 className="w-3 h-3 animate-spin" /> : <FilePen className="w-3 h-3" />}
                                  {t("proposePatch")}
                                </button>
                              )}
                              <button
                                onClick={() => resolve(inc, "validated")}
                                disabled={busyId === inc.id}
                                className="flex items-center gap-1 px-2 py-1 text-[11px] rounded border border-emerald-500/30 text-emerald-300 hover:bg-emerald-500/10 transition-colors disabled:opacity-50"
                                title={t("validateHint")}
                              >
                                {busyId === inc.id ? <Loader2 className="w-3 h-3 animate-spin" /> : <CheckCircle2 className="w-3 h-3" />}
                                {t("validate")}
                              </button>
                              <button
                                onClick={() => resolve(inc, "rejected")}
                                disabled={busyId === inc.id}
                                className="flex items-center gap-1 px-2 py-1 text-[11px] rounded border border-border-dim text-text-muted hover:text-red-300 hover:border-red-500/30 transition-colors disabled:opacity-50"
                                title={t("rejectHint")}
                              >
                                {busyId === inc.id ? <Loader2 className="w-3 h-3 animate-spin" /> : <ThumbsDown className="w-3 h-3" />}
                                {t("reject")}
                              </button>
                            </div>
                          )}
                        </div>
                      </li>
                    );
                  })}
                </ul>
              </section>
            )}
          </main>
        </div>
        </div>
      </div>

      {/* Confirmation modal for "Generate tool" — paid LLM call. */}
      {confirmGen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
          <div className="bg-bg-secondary border border-border-dim rounded-lg max-w-md w-full mx-4 p-5 space-y-3">
            <div className="flex items-center gap-2">
              <AlertTriangle className="w-5 h-5 text-cyber-cyan" />
              <h2 className="text-sm font-medium text-text-primary">{t("confirmTitle")}</h2>
            </div>
            <p className="text-xs text-text-secondary">{t("confirmBody")}</p>
            <p className="text-xs text-text-muted bg-bg-primary border border-border-dim rounded p-2 font-mono">
              {confirmGen.hypothesis}
            </p>
            <div className="flex items-center gap-2 justify-end">
              <button
                onClick={() => setConfirmGen(null)}
                className="px-3 py-1.5 text-[11px] rounded border border-border-dim text-text-muted hover:text-text-secondary"
              >
                {t("cancel")}
              </button>
              <button
                onClick={() => generateTool(confirmGen)}
                className="px-3 py-1.5 text-[11px] rounded border border-cyber-cyan/30 text-cyber-cyan hover:bg-cyber-cyan/10 flex items-center gap-1"
              >
                <Wrench className="w-3 h-3" />
                {t("confirmGenerate")}
              </button>
            </div>
          </div>
        </div>
      )}
    </AdminGuard>
  );
}
