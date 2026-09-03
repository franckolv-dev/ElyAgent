"use client";
/**
 * @project    ELY — Exactly Like You
 * @file       frontend/src/app/missions/page.tsx
 * @brief      Missions list — goal-driven persistence loop dashboard
 *
 * @author     Franck OLLIVIER <contact@agent-ely.fr>
 * @copyright  Copyright (c) 2025-2026 Franck OLLIVIER
 * @license    MIT
 *            https://opensource.org/licenses/MIT
 */

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useTranslations } from "next-intl";
import { AuthGuard } from "@/components/layout/AuthGuard";
import { Sidebar } from "@/components/layout/Sidebar";
import { Header } from "@/components/layout/Header";
import { Target, Plus, Loader2, AlertCircle, X, RefreshCw, Trash2, Pencil } from "lucide-react";
import { useRouter } from "next/navigation";
import {
  missionsApi, type Mission, type MissionStatus, STATUS_META,
} from "@/lib/missions";
import {
  MANDATE_TOOL_FAMILIES, MANDATE_FORM_DEFAULTS, buildMandateSpecYaml,
  type MandateFormValues,
} from "@/lib/mandate";

type FilterTab = "all" | "active" | "terminal";

export default function MissionsPage() {
  const t = useTranslations("missions");
  const [missions, setMissions] = useState<Mission[]>([]);
  const [loading, setLoading]   = useState(true);
  const [error, setError]       = useState<string | null>(null);
  const [filter, setFilter]     = useState<FilterTab>("all");
  const [showCreate, setShowCreate] = useState(false);
  const [editMission, setEditMission] = useState<Mission | null>(null);

  const fetchAll = useCallback(async () => {
    setError(null);
    try {
      const data = await missionsApi.list();
      setMissions(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : t("loadError"));
    } finally {
      setLoading(false);
    }
  }, [t]);

  useEffect(() => { fetchAll(); }, [fetchAll]);

  // Auto-refresh every 5 s if any mission is active (running/planning)
  useEffect(() => {
    const hasActive = missions.some((m) => m.status === "running" || m.status === "planning");
    if (!hasActive) return;
    const t = setInterval(fetchAll, 5_000);
    return () => clearInterval(t);
  }, [missions, fetchAll]);

  const filtered = missions.filter((m) => {
    if (filter === "active") return ["draft", "planning", "running", "paused"].includes(m.status);
    if (filter === "terminal") return ["completed", "failed", "aborted"].includes(m.status);
    return true;
  });

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
                <Target className="w-5 h-5 text-cyber-cyan" />
                <h1 className="text-lg font-medium text-text-primary">{t("title")}</h1>
                <span className="text-[11px] text-text-muted">
                  {t("subtitle")}
                </span>
              </div>
              <button
                onClick={() => setShowCreate(true)}
                className="btn primary"
              >
                <Plus size={14} />
                {t("newMission")}
              </button>
            </div>

            {/* Tabs */}
            <div className="flex gap-1 border-b border-border-dim">
              {(["all", "active", "terminal"] as FilterTab[]).map((tab) => (
                <button
                  key={tab}
                  onClick={() => setFilter(tab)}
                  className={`text-xs px-3 py-2 -mb-px border-b-2 transition-all ${
                    filter === tab
                      ? "border-cyber-cyan text-cyber-cyan"
                      : "border-transparent text-text-muted hover:text-text-secondary"
                  }`}
                >
                  {tab === "all" ? t("tabAll") : tab === "active" ? t("tabActive") : t("tabTerminal")}
                  <span className="ml-1.5 text-[10px] text-text-muted">
                    ({tab === "all" ? missions.length :
                       tab === "active" ? missions.filter(m => ["draft","planning","running","paused"].includes(m.status)).length :
                       missions.filter(m => ["completed","failed","aborted"].includes(m.status)).length})
                  </span>
                </button>
              ))}
            </div>

            {/* List */}
            {error && (
              <div className="flex items-center gap-2 text-xs text-red-400 bg-red-500/10 border border-red-500/20 rounded px-3 py-2">
                <AlertCircle className="w-4 h-4" />
                {error}
              </div>
            )}

            {loading ? (
              <div className="flex items-center justify-center py-12 text-text-muted">
                <Loader2 className="w-5 h-5 animate-spin mr-2" /> {t("loading")}
              </div>
            ) : filtered.length === 0 ? (
              <div className="text-center py-12 text-text-muted text-sm">
                {filter === "all"
                  ? t("emptyAll")
                  : filter === "active"
                  ? t("emptyActive")
                  : t("emptyTerminal")}
              </div>
            ) : (
              <div className="space-y-2">
                {filtered.map((m) => (
                  <MissionCard key={m.id} mission={m} onChanged={fetchAll} onEdit={setEditMission} />
                ))}
              </div>
            )}

          {showCreate && (
            <CreateMissionModal
              onClose={() => setShowCreate(false)}
              onCreated={() => { setShowCreate(false); fetchAll(); }}
            />
          )}
          {editMission && (
            <CreateMissionModal
              mission={editMission}
              onClose={() => setEditMission(null)}
              onCreated={() => { setEditMission(null); fetchAll(); }}
            />
          )}
          </main>
        </div>
        </div>
      </div>
    </AuthGuard>
  );
}

// ── Mission card ────────────────────────────────────────────────────────────

function MissionCard({ mission, onChanged, onEdit }: { mission: Mission; onChanged: () => void; onEdit: (m: Mission) => void }) {
  const t = useTranslations("missions");
  const router = useRouter();
  const meta = STATUS_META[mission.status];
  const progress = mission.budget_iterations
    ? Math.round((mission.iterations_used / mission.budget_iterations) * 100)
    : 0;
  const isTerminal = ["failed", "completed", "aborted"].includes(mission.status);

  const [busy, setBusy] = useState<null | "restart" | "delete">(null);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [actionError, setActionError] = useState("");

  const handleRestart = async (e: React.MouseEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setBusy("restart");
    setActionError("");
    try {
      await missionsApi.restart(mission.id);
      onChanged();
    } catch (err) {
      setActionError(err instanceof Error ? err.message : t("restartFailed"));
    } finally {
      setBusy(null);
    }
  };

  const handleDelete = async (e: React.MouseEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setBusy("delete");
    setActionError("");
    try {
      await missionsApi.remove(mission.id);
      onChanged();
    } catch (err) {
      setActionError(err instanceof Error ? err.message : t("deleteFailed"));
      setConfirmDelete(false);
    } finally {
      setBusy(null);
    }
  };

  return (
    <div
      onClick={() => router.push(`/missions/${mission.id}`)}
      className="block bg-bg-secondary border border-border-dim hover:border-cyber-cyan/40 rounded-lg p-4 transition-all cursor-pointer"
    >
      <div className="flex items-start justify-between gap-3">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-1">
            <h3 className="text-sm font-medium text-text-primary truncate">{mission.title}</h3>
            <span className={`inline-flex items-center gap-1 text-[10px] px-1.5 py-0.5 rounded border ${meta.color} shrink-0`}>
              {meta.emoji} {meta.label}
            </span>
          </div>
          <p className="text-[11px] text-text-muted line-clamp-2">{mission.goal}</p>
        </div>

        {/* Action buttons — visible only on terminal missions for now to
            avoid accidental restart/delete of a running one. The detail
            page can offer a "force-stop then delete" flow later. */}
        {isTerminal && (
          <div className="flex items-center gap-1 shrink-0" onClick={(e) => e.stopPropagation()}>
            <button
              type="button"
              onClick={(e) => { e.preventDefault(); e.stopPropagation(); onEdit(mission); }}
              disabled={busy !== null}
              title={t("editTooltip")}
              className="p-1.5 text-text-muted hover:text-cyber-cyan hover:bg-cyber-cyan/10 rounded transition-colors disabled:opacity-50"
            >
              <Pencil className="w-3.5 h-3.5" />
            </button>
            <button
              type="button"
              onClick={handleRestart}
              disabled={busy !== null}
              title={t("restartTooltip")}
              className="p-1.5 text-text-muted hover:text-cyber-cyan hover:bg-cyber-cyan/10 rounded transition-colors disabled:opacity-50"
            >
              {busy === "restart"
                ? <Loader2 className="w-3.5 h-3.5 animate-spin" />
                : <RefreshCw className="w-3.5 h-3.5" />}
            </button>
            <button
              type="button"
              onClick={(e) => {
                e.preventDefault();
                e.stopPropagation();
                setConfirmDelete(true);
              }}
              disabled={busy !== null}
              title={t("deleteTooltip")}
              className="p-1.5 text-text-muted hover:text-red-400 hover:bg-red-500/10 rounded transition-colors disabled:opacity-50"
            >
              <Trash2 className="w-3.5 h-3.5" />
            </button>
          </div>
        )}
      </div>

      <div className="mt-3 flex items-center gap-4 text-[10px] text-text-muted">
        <span title={t("iterationsTooltip")}>
          ⚙️ {mission.iterations_used}/{mission.budget_iterations}
        </span>
        <span title={t("tokensTooltip")}>
          🔢 {mission.tokens_used.toLocaleString()}/{mission.budget_tokens.toLocaleString()}
        </span>
        <span>📅 {new Date(mission.created_at).toLocaleDateString("fr-FR", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" })}</span>
        {mission.tick_interval_seconds && (
          <span title={t("tickIntervalTooltip")}>{t("tickEvery", { seconds: mission.tick_interval_seconds })}</span>
        )}
        {mission.autonomous && (
          <span
            title={t("autonomousHint")}
            className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded bg-cyber-cyan/10 border border-cyber-cyan/30 text-cyber-cyan"
          >
            🤖 {t("autonomousBadge")}
          </span>
        )}
        {mission.autonomy_state === "pending_validation" && (
          <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded bg-amber-500/10 border border-amber-500/30 text-amber-300">
            🛡️ {t("mandatePendingBadge")}
          </span>
        )}
        {mission.autonomy_state === "active" && (
          <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded bg-cyber-cyan/10 border border-cyber-cyan/30 text-cyber-cyan">
            🛡️ {t("mandateActiveBadge")}
          </span>
        )}
        {(mission.autonomy_state || "").startsWith("paused") && (
          <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded bg-amber-500/10 border border-amber-500/30 text-amber-300">
            🛡️ {t("mandatePausedBadge")}
          </span>
        )}
      </div>

      {/* Progress bar */}
      <div className="mt-2 h-1 bg-bg-primary rounded overflow-hidden">
        <div
          className={`h-full transition-all ${mission.status === "completed" ? "bg-emerald-400" : mission.status === "failed" || mission.status === "aborted" ? "bg-red-400/50" : "bg-cyber-cyan"}`}
          style={{ width: `${Math.min(100, progress)}%` }}
        />
      </div>

      {/* Final state preview */}
      {mission.final_summary && (
        <p className="mt-2 text-[11px] text-emerald-300/80 line-clamp-1">✓ {mission.final_summary}</p>
      )}
      {mission.failure_reason && (
        <p className="mt-2 text-[11px] text-red-300/80 line-clamp-1">⚠ {mission.failure_reason}</p>
      )}
      {actionError && (
        <p className="mt-2 text-[11px] text-red-400 line-clamp-2">{actionError}</p>
      )}

      {/* Confirm-delete inline sheet */}
      {confirmDelete && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/60"
          onClick={(e) => { e.stopPropagation(); setConfirmDelete(false); }}
        >
          <div
            className="bg-bg-secondary border border-red-500/30 rounded-lg p-5 w-full max-w-md mx-4 space-y-3"
            onClick={(e) => e.stopPropagation()}
          >
            <h4 className="text-sm font-semibold text-red-400">{t("deleteModalTitle")}</h4>
            <p className="text-xs text-text-secondary">
              {t("deleteModalBody", { title: mission.title })}
            </p>
            <div className="flex justify-end gap-2 pt-1">
              <button
                type="button"
                onClick={(e) => { e.preventDefault(); e.stopPropagation(); setConfirmDelete(false); }}
                disabled={busy === "delete"}
                className="text-xs px-3 py-1.5 rounded border border-border-dim text-text-secondary hover:text-text-primary"
              >
                {t("cancel")}
              </button>
              <button
                type="button"
                onClick={handleDelete}
                disabled={busy === "delete"}
                className="text-xs px-3 py-1.5 rounded bg-red-500/10 border border-red-500/30 text-red-400 hover:bg-red-500/20 flex items-center gap-1.5"
              >
                {busy === "delete" && <Loader2 className="w-3 h-3 animate-spin" />}
                <span>{t("deleteConfirm")}</span>
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

// ── Create modal ────────────────────────────────────────────────────────────

function CreateMissionModal({ onClose, onCreated, mission }: { onClose: () => void; onCreated: () => void; mission?: Mission }) {
  const t = useTranslations("missions");
  const isEdit = !!mission;
  const [title, setTitle]   = useState(mission?.title ?? "");
  const [goal, setGoal]     = useState(mission?.goal ?? "");
  const [budgetIter, setBudgetIter] = useState(mission?.budget_iterations ?? 15);
  const [budgetTok, setBudgetTok]   = useState(mission?.budget_tokens ?? 500_000);
  const [autonomous, setAutonomous] = useState(mission?.autonomous ?? false);
  // Sprint 4c — spec structurée optionnelle (création uniquement)
  const [specYaml, setSpecYaml] = useState("");
  const [showSpec, setShowSpec] = useState(false);
  // C6 — formulaire de mandat : génère la spec v2 (fin du piège « le mandat
  // se déclare à la main dans le YAML »).
  const [showMandate, setShowMandate] = useState(false);
  const [mandate, setMandate] = useState<MandateFormValues>(MANDATE_FORM_DEFAULTS);
  const [busy, setBusy]     = useState(false);
  const [err, setErr]       = useState<string | null>(null);

  const toggleFamily = (fam: string) => {
    setMandate((m) => ({
      ...m,
      toolsAllow: m.toolsAllow.includes(fam)
        ? m.toolsAllow.filter((f) => f !== fam)
        : [...m.toolsAllow, fam],
    }));
  };

  const generateMandateSpec = () => {
    if (specYaml.trim() && !window.confirm(t("mandateReplaceConfirm"))) return;
    setSpecYaml(buildMandateSpecYaml(mandate));
    setShowSpec(true);
  };

  const submit = async () => {
    if (!title.trim() || goal.trim().length < 5) {
      setErr(t("validationError"));
      return;
    }
    setBusy(true);
    setErr(null);
    const body = {
      title: title.trim(),
      goal: goal.trim(),
      budget_iterations: budgetIter,
      budget_tokens: budgetTok,
      autonomous,
      // Sprint 4c — le serveur valide la spec (422 avec TOUTES les erreurs)
      ...(!isEdit && specYaml.trim() ? { spec_yaml: specYaml } : {}),
    };
    try {
      if (isEdit) {
        await missionsApi.update(mission!.id, body);
      } else {
        await missionsApi.create(body);
      }
      onCreated();
    } catch (e) {
      setErr(e instanceof Error ? e.message : t("createError"));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center z-50 p-4">
      <div className="bg-bg-primary border border-border-dim rounded-lg w-full max-w-xl shadow-xl">
        <div className="flex items-center justify-between p-4 border-b border-border-dim">
          <h2 className="text-sm font-medium text-text-primary">{isEdit ? t("editMission") : t("newMission")}</h2>
          <button onClick={onClose} className="text-text-muted hover:text-text-primary"><X className="w-4 h-4" /></button>
        </div>

        <div className="p-4 space-y-3">
          <div>
            <label className="text-[11px] text-text-muted block mb-1">{t("titleLabel")}</label>
            <input
              type="text"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder={t("titlePlaceholder")}
              className="w-full text-sm bg-bg-secondary border border-border-dim rounded px-3 py-2 text-text-primary placeholder:text-text-muted focus:outline-none focus:border-cyber-cyan/40"
            />
          </div>

          <div>
            <label className="text-[11px] text-text-muted block mb-1">{t("goalLabel")}</label>
            <textarea
              value={goal}
              onChange={(e) => setGoal(e.target.value)}
              placeholder={t("goalPlaceholder")}
              rows={5}
              className="w-full text-sm bg-bg-secondary border border-border-dim rounded px-3 py-2 text-text-primary placeholder:text-text-muted focus:outline-none focus:border-cyber-cyan/40 resize-none"
            />
          </div>

          {!isEdit && (
            <div>
              <button
                type="button"
                onClick={() => setShowSpec(!showSpec)}
                className="text-[11px] text-cyber-cyan hover:underline"
              >
                {showSpec ? "▾ " : "▸ "}{t("specToggle")}
              </button>
              {showSpec && (
                <div className="mt-1">
                  <textarea
                    value={specYaml}
                    onChange={(e) => setSpecYaml(e.target.value)}
                    placeholder={t("specPlaceholder")}
                    rows={10}
                    spellCheck={false}
                    className="w-full text-[12px] font-mono bg-bg-secondary border border-border-dim rounded px-3 py-2 text-text-primary placeholder:text-text-muted focus:outline-none focus:border-cyber-cyan/40 resize-y"
                  />
                  <p className="text-[10px] text-text-muted mt-1">{t("specHint")}</p>
                </div>
              )}

              {/* C6 — formulaire de mandat d'autonomie → génère la spec v2 */}
              <div className="mt-2">
                <button
                  type="button"
                  onClick={() => setShowMandate(!showMandate)}
                  className="text-[11px] text-cyber-cyan hover:underline"
                >
                  {showMandate ? "▾ " : "▸ "}{t("mandateToggle")}
                </button>
                {showMandate && (
                  <div className="mt-2 space-y-2 border border-border-dim rounded p-3 bg-bg-secondary/50">
                    <p className="text-[10px] text-text-muted">{t("mandateIntro")}</p>
                    <div>
                      <span className="text-[11px] text-text-muted block mb-1">{t("mandateFamilies")}</span>
                      <div className="grid grid-cols-4 gap-x-2 gap-y-1">
                        {MANDATE_TOOL_FAMILIES.map((fam) => (
                          <label key={fam} className="flex items-center gap-1 text-[10px] text-text-primary cursor-pointer select-none">
                            <input
                              type="checkbox"
                              checked={mandate.toolsAllow.includes(fam)}
                              onChange={() => toggleFamily(fam)}
                              className="accent-cyan-400 w-3 h-3"
                            />
                            {fam}
                          </label>
                        ))}
                      </div>
                    </div>
                    <div className="grid grid-cols-3 gap-2">
                      <label className="text-[10px] text-text-muted">
                        {t("mandateAutonomy")}
                        <select
                          value={mandate.autonomy}
                          onChange={(e) => setMandate({ ...mandate, autonomy: e.target.value as MandateFormValues["autonomy"] })}
                          className="mt-1 w-full text-[11px] bg-bg-secondary border border-border-dim rounded px-1.5 py-1 text-text-primary"
                        >
                          <option value="autonomous">autonomous</option>
                          <option value="supervised">supervised</option>
                        </select>
                      </label>
                      <label className="text-[10px] text-text-muted">
                        {t("mandateOnUnforeseen")}
                        <select
                          value={mandate.onUnforeseen}
                          onChange={(e) => setMandate({ ...mandate, onUnforeseen: e.target.value as MandateFormValues["onUnforeseen"] })}
                          className="mt-1 w-full text-[11px] bg-bg-secondary border border-border-dim rounded px-1.5 py-1 text-text-primary"
                        >
                          <option value="escalate">escalate</option>
                          <option value="decide">decide</option>
                        </select>
                      </label>
                      <label className="text-[10px] text-text-muted">
                        {t("mandateLlmTier")}
                        <select
                          value={mandate.llmTier}
                          onChange={(e) => setMandate({ ...mandate, llmTier: e.target.value as MandateFormValues["llmTier"] })}
                          className="mt-1 w-full text-[11px] bg-bg-secondary border border-border-dim rounded px-1.5 py-1 text-text-primary"
                        >
                          <option value="">{t("mandateTierDefault")}</option>
                          <option value="simple">simple</option>
                          <option value="medium">medium</option>
                          <option value="complex">complex</option>
                        </select>
                      </label>
                    </div>
                    <div className="grid grid-cols-2 gap-2">
                      <label className="text-[10px] text-text-muted">
                        {t("mandateBudgetTools")}
                        <input
                          type="number" min={1} value={mandate.dailyToolActionsNotify}
                          onChange={(e) => setMandate({ ...mandate, dailyToolActionsNotify: Math.max(1, +e.target.value || 1) })}
                          className="mt-1 w-full text-[11px] bg-bg-secondary border border-border-dim rounded px-1.5 py-1 text-text-primary"
                        />
                      </label>
                      <label className="text-[10px] text-text-muted">
                        {t("mandateBudgetLlm")}
                        <input
                          type="number" min={1} value={mandate.dailyLlmCallsNotify}
                          onChange={(e) => setMandate({ ...mandate, dailyLlmCallsNotify: Math.max(1, +e.target.value || 1) })}
                          className="mt-1 w-full text-[11px] bg-bg-secondary border border-border-dim rounded px-1.5 py-1 text-text-primary"
                        />
                      </label>
                    </div>
                    <div className="flex items-center justify-between gap-2">
                      <span className="text-[10px] text-text-muted">{t("mandateCoreHint")}</span>
                      <button
                        type="button"
                        onClick={generateMandateSpec}
                        disabled={mandate.toolsAllow.length === 0}
                        className="text-[11px] px-2.5 py-1 rounded border border-cyber-cyan/30 bg-cyber-cyan/10 text-cyber-cyan hover:bg-cyber-cyan/20 disabled:opacity-40 shrink-0"
                      >
                        {t("mandateGenerate")}
                      </button>
                    </div>
                  </div>
                )}
              </div>
            </div>
          )}

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-[11px] text-text-muted block mb-1">
                {t("budgetIterations")} <span className="text-text-muted/60">{t("maxTicks")}</span>
              </label>
              <input
                type="number" min={1} max={200} value={budgetIter}
                onChange={(e) => setBudgetIter(Math.max(1, Math.min(200, +e.target.value || 1)))}
                className="w-full text-sm bg-bg-secondary border border-border-dim rounded px-3 py-2 text-text-primary focus:outline-none focus:border-cyber-cyan/40"
              />
            </div>
            <div>
              <label className="text-[11px] text-text-muted block mb-1">
                {t("budgetTokens")} <span className="text-text-muted/60">{t("llmHint")}</span>
              </label>
              <input
                type="number" min={1000} max={5_000_000} step={1000} value={budgetTok}
                onChange={(e) => setBudgetTok(Math.max(1000, Math.min(5_000_000, +e.target.value || 1000)))}
                className="w-full text-sm bg-bg-secondary border border-border-dim rounded px-3 py-2 text-text-primary focus:outline-none focus:border-cyber-cyan/40"
              />
            </div>
          </div>

          {/* Autonomous mode — auto-approve safe HITL so scheduled/overnight
              runs don't stall (dangerous actions still require a human). */}
          <label className="flex items-start gap-2 cursor-pointer select-none">
            <input
              type="checkbox"
              checked={autonomous}
              onChange={(e) => setAutonomous(e.target.checked)}
              className="mt-0.5 accent-cyber-cyan"
            />
            <span className="text-[11px] text-text-muted">
              <span className="text-text-primary">{t("autonomousLabel")}</span>
              <br />
              {t("autonomousHint")}
            </span>
          </label>

          {err && (
            <div className="flex items-center gap-2 text-xs text-red-400 bg-red-500/10 border border-red-500/20 rounded px-2 py-1.5">
              <AlertCircle className="w-3.5 h-3.5" />
              {err}
            </div>
          )}

          <p className="text-[10px] text-text-muted">
            {t.rich("draftHint", { strong: (chunks) => <strong>{chunks}</strong> })}
          </p>
        </div>

        <div className="flex justify-end gap-2 p-4 border-t border-border-dim">
          <button
            onClick={onClose}
            disabled={busy}
            className="text-xs px-3 py-1.5 rounded border border-border-dim text-text-muted hover:text-text-secondary"
          >
            {t("cancel")}
          </button>
          <button
            onClick={submit}
            disabled={busy || !title.trim() || goal.trim().length < 5}
            className="text-xs px-3 py-1.5 rounded border border-cyber-cyan/30 text-cyber-cyan hover:bg-cyber-cyan/5 disabled:opacity-50"
          >
            {busy
              ? (isEdit ? t("saving") : t("creating"))
              : (isEdit ? t("saveMission") : t("createMission"))}
          </button>
        </div>
      </div>
    </div>
  );
}
