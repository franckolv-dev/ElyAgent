"use client";
/**
 * @project    ELY — Exactly Like You
 * @file       frontend/src/app/me/learning/skills/page.tsx
 * @brief      Sprint 4b Phase 5.b — user-facing list of the playbooks ELY
 *             has written for me from my own signals (refus HITL,
 *             hallucinations, critiques). Backed by
 *             `/api/me/learning-skills` (list / pin / forget). The page
 *             groups skills by status, lets the user expand the full
 *             Markdown body, pin a high-value skill so the curator
 *             leaves it alone, or "forget" a skill (archive — admin
 *             can still restore).
 *
 * @author     Franck OLLIVIER <contact@agent-ely.fr>
 * @copyright  Copyright (c) 2025-2026 Franck OLLIVIER
 * @license    MIT
 * @version    1.10.0
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslations } from "next-intl";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import {
  Sparkles, Loader2, AlertCircle, RefreshCw, Pin, PinOff,
  Eraser, ChevronDown, ChevronRight,
} from "lucide-react";

import { AuthGuard } from "@/components/layout/AuthGuard";
import { Sidebar } from "@/components/layout/Sidebar";
import { Header } from "@/components/layout/Header";
import { api, type MeLearnedSkill } from "@/lib/api";

// ── Status → group ordering ────────────────────────────────────────────────
// Mirrors the backend ordering hint: active first (production), then the
// "still in flight" / "dormant" / terminal states. Candidate sits between
// active and stale because it's an in-progress signal worth seeing.
const STATUS_ORDER = [
  "active",
  "candidate",
  "stale",
  "archived",
  "rejected",
] as const;

type Status = (typeof STATUS_ORDER)[number];

function statusBadgeClass(s: string): string {
  switch (s) {
    case "active":
      return "bg-emerald-500/10 text-emerald-300 border-emerald-500/30";
    case "candidate":
      return "bg-cyber-cyan/10 text-cyber-cyan border-cyber-cyan/30";
    case "stale":
      return "bg-amber-500/10 text-amber-300 border-amber-500/30";
    case "archived":
      return "bg-text-muted/10 text-text-muted border-border-dim";
    case "rejected":
      return "bg-red-500/10 text-red-300 border-red-500/30";
    default:
      return "bg-bg-primary text-text-muted border-border-dim";
  }
}

function fmtDate(iso: string | null): string {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleDateString("fr-FR", {
      day: "2-digit",
      month: "short",
      year: "2-digit",
    });
  } catch {
    return iso;
  }
}

export default function LearningSkillsPage() {
  const t = useTranslations("learningSkills");

  const [skills, setSkills]   = useState<MeLearnedSkill[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError]     = useState<string | null>(null);

  // ── Expansion state (one open at a time keeps the layout calm) ──────────
  const [expandedId, setExpandedId] = useState<string | null>(null);

  // ── Per-row mutation state — prevent double-clicks on the same id ───────
  const [busyId, setBusyId] = useState<string | null>(null);

  // ── Forget confirmation modal target ────────────────────────────────────
  const [confirmForgetId, setConfirmForgetId] = useState<string | null>(null);

  const fetchSkills = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await api.myLearningSkillsList();
      setSkills(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : t("errorLoad"));
    } finally {
      setLoading(false);
    }
  }, [t]);

  useEffect(() => {
    fetchSkills();
  }, [fetchSkills]);

  const togglePin = async (s: MeLearnedSkill) => {
    if (busyId) return;
    setBusyId(s.id);
    try {
      const updated = await api.myLearningSkillPin(s.id, !s.pinned);
      // Optimistic replace in-place rather than full re-fetch — keeps
      // the expand state and the user's scroll position.
      setSkills((cur) =>
        cur.map((row) => (row.id === updated.id ? updated : row)),
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : "Erreur");
    } finally {
      setBusyId(null);
    }
  };

  const confirmForget = async () => {
    if (!confirmForgetId || busyId) return;
    setBusyId(confirmForgetId);
    try {
      const updated = await api.myLearningSkillForget(confirmForgetId);
      setSkills((cur) =>
        cur.map((row) => (row.id === updated.id ? updated : row)),
      );
      setConfirmForgetId(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Erreur");
    } finally {
      setBusyId(null);
    }
  };

  // ── Group by status, in STATUS_ORDER ────────────────────────────────────
  const grouped = useMemo(() => {
    const byStatus = new Map<Status, MeLearnedSkill[]>();
    for (const s of STATUS_ORDER) byStatus.set(s, []);
    for (const row of skills) {
      const bucket = (STATUS_ORDER as readonly string[]).includes(row.status)
        ? (row.status as Status)
        : "archived";
      byStatus.get(bucket)!.push(row);
    }
    return byStatus;
  }, [skills]);

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
            {/* ── Header ──────────────────────────────────────────────── */}
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div className="flex items-center gap-3">
                <Sparkles className="w-5 h-5 text-cyber-cyan" />
                <h1 className="text-lg font-medium text-text-primary">
                  {t("title")}
                </h1>
                <span className="text-[11px] text-text-muted">
                  {t("subtitle")}
                </span>
              </div>

              <button
                onClick={fetchSkills}
                disabled={loading}
                className="p-1.5 text-text-muted hover:text-cyber-cyan hover:bg-cyber-cyan/10 rounded transition-colors disabled:opacity-50"
                title={t("refreshTooltip")}
              >
                {loading ? (
                  <Loader2 className="w-3.5 h-3.5 animate-spin" />
                ) : (
                  <RefreshCw className="w-3.5 h-3.5" />
                )}
              </button>
            </div>

            {/* ── Errors ─────────────────────────────────────────────── */}
            {error && (
              <div className="flex items-center gap-2 text-xs text-red-400 bg-red-500/10 border border-red-500/20 rounded px-3 py-2">
                <AlertCircle className="w-4 h-4" />
                {error}
              </div>
            )}

            {/* ── Loading ────────────────────────────────────────────── */}
            {loading && !error && (
              <div className="flex items-center justify-center py-12 text-text-muted">
                <Loader2 className="w-5 h-5 animate-spin mr-2" />
                {t("loading")}
              </div>
            )}

            {/* ── Empty state ───────────────────────────────────────── */}
            {!loading && !error && skills.length === 0 && (
              <div className="bg-bg-secondary border border-border-dim rounded-lg p-8 text-center">
                <Sparkles className="w-8 h-8 text-text-muted mx-auto mb-3" />
                <p className="text-sm text-text-secondary">{t("empty")}</p>
              </div>
            )}

            {/* ── Groups ────────────────────────────────────────────── */}
            {!loading && !error && skills.length > 0 && (
              <div className="space-y-6">
                {STATUS_ORDER.map((s) => {
                  const rows = grouped.get(s)!;
                  if (rows.length === 0) return null;
                  return (
                    <SkillGroup
                      key={s}
                      status={s}
                      rows={rows}
                      expandedId={expandedId}
                      onToggleExpand={(id) =>
                        setExpandedId((cur) => (cur === id ? null : id))
                      }
                      onTogglePin={togglePin}
                      onForget={(id) => setConfirmForgetId(id)}
                      busyId={busyId}
                    />
                  );
                })}
              </div>
            )}

            {/* ── Privacy note ──────────────────────────────────────── */}
            <p className="text-[10px] text-text-muted pt-2 border-t border-border-dim">
              {t("privacyNote")}
            </p>
          </main>
        </div>
        </div>
      </div>

      {/* ── Forget confirmation modal ───────────────────────────────── */}
      {confirmForgetId && (
        <ConfirmForgetModal
          onCancel={() => setConfirmForgetId(null)}
          onConfirm={confirmForget}
          busy={busyId === confirmForgetId}
        />
      )}
    </AuthGuard>
  );
}

// ───────────────────────────────────────────────────────────────────────────
// Group section — one card per status with a header + a list of rows.
// ───────────────────────────────────────────────────────────────────────────

function SkillGroup({
  status,
  rows,
  expandedId,
  onToggleExpand,
  onTogglePin,
  onForget,
  busyId,
}: {
  status: Status;
  rows: MeLearnedSkill[];
  expandedId: string | null;
  onToggleExpand: (id: string) => void;
  onTogglePin: (s: MeLearnedSkill) => Promise<void>;
  onForget: (id: string) => void;
  busyId: string | null;
}) {
  const t = useTranslations("learningSkills");
  const groupKey = `group${status.charAt(0).toUpperCase() + status.slice(1)}` as
    | "groupActive" | "groupCandidate" | "groupStale" | "groupArchived" | "groupRejected";

  return (
    <section className="bg-bg-secondary border border-border-dim rounded-lg overflow-hidden">
      <header className="flex items-center gap-2 px-4 py-3 border-b border-border-dim">
        <span
          className={`px-2 py-0.5 text-[10px] font-mono rounded border ${statusBadgeClass(status)}`}
        >
          {status}
        </span>
        <h2 className="text-sm font-medium text-text-primary">
          {t(groupKey)}
        </h2>
        <span className="ml-auto text-[10px] text-text-muted">{rows.length}</span>
      </header>
      <ul className="divide-y divide-border-dim/50">
        {rows.map((s) => (
          <SkillRow
            key={s.id}
            skill={s}
            expanded={expandedId === s.id}
            onToggleExpand={() => onToggleExpand(s.id)}
            onTogglePin={() => onTogglePin(s)}
            onForget={() => onForget(s.id)}
            busy={busyId === s.id}
          />
        ))}
      </ul>
    </section>
  );
}

// ───────────────────────────────────────────────────────────────────────────
// Row — one playbook : header + metadata + actions + expandable body.
// ───────────────────────────────────────────────────────────────────────────

function SkillRow({
  skill,
  expanded,
  onToggleExpand,
  onTogglePin,
  onForget,
  busy,
}: {
  skill: MeLearnedSkill;
  expanded: boolean;
  onToggleExpand: () => void;
  onTogglePin: () => Promise<void>;
  onForget: () => void;
  busy: boolean;
}) {
  const t = useTranslations("learningSkills");
  const sourceKey = `source${skill.source
    .split("_")
    .map((p) => p.charAt(0).toUpperCase() + p.slice(1))
    .join("")}` as
    | "sourceAutoGenerated"
    | "sourceUserAdded"
    | "sourceImportedMarketplace";
  // The forget action is meaningless on archived/rejected — we hide it
  // rather than disable it, to keep the affordance honest.
  const canForget = skill.status !== "archived" && skill.status !== "rejected";

  return (
    <li className="px-4 py-3">
      <div className="flex items-start gap-3">
        {/* Expand chevron */}
        <button
          onClick={onToggleExpand}
          className="mt-0.5 text-text-muted hover:text-cyber-cyan transition-colors"
          title={expanded ? t("collapse") : t("expand")}
        >
          {expanded ? (
            <ChevronDown className="w-4 h-4" />
          ) : (
            <ChevronRight className="w-4 h-4" />
          )}
        </button>

        <div className="flex-1 min-w-0">
          {/* Top line : name + pinned badge */}
          <div className="flex items-center gap-2 flex-wrap">
            <code className="text-sm font-medium text-text-primary truncate">
              {skill.name}
            </code>
            {skill.pinned && (
              <span className="text-[10px] text-cyber-cyan flex items-center gap-1">
                <Pin className="w-3 h-3" /> pinned
              </span>
            )}
            <span className="text-[10px] text-text-muted ml-auto">
              {t(sourceKey)}
            </span>
          </div>

          {/* Description */}
          <p className="text-xs text-text-secondary mt-1 line-clamp-2">
            {skill.description}
          </p>

          {/* Metadata row */}
          <div className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-0.5 text-[10px] text-text-muted">
            <span>{t("iterationsLabel", { n: skill.iteration_count })}</span>
            {skill.last_eval_score !== null && (
              <span>{t("scoreLabel", { score: skill.last_eval_score })}</span>
            )}
            <span>{t("useCountLabel", { n: skill.use_count })}</span>
            <span>
              {skill.last_used_at
                ? t("lastUsedLabel", { date: fmtDate(skill.last_used_at) })
                : t("neverUsed")}
            </span>
          </div>
        </div>

        {/* Actions */}
        <div className="flex items-center gap-1 shrink-0">
          <button
            onClick={onTogglePin}
            disabled={busy}
            className="p-1.5 text-text-muted hover:text-cyber-cyan hover:bg-cyber-cyan/10 rounded transition-colors disabled:opacity-50"
            title={skill.pinned ? t("unpinLabel") : t("pinLabel")}
          >
            {skill.pinned ? (
              <PinOff className="w-3.5 h-3.5" />
            ) : (
              <Pin className="w-3.5 h-3.5" />
            )}
          </button>
          {canForget && (
            <button
              onClick={onForget}
              disabled={busy}
              className="p-1.5 text-text-muted hover:text-red-400 hover:bg-red-500/10 rounded transition-colors disabled:opacity-50"
              title={t("forgetHint")}
            >
              <Eraser className="w-3.5 h-3.5" />
            </button>
          )}
        </div>
      </div>

      {/* Expanded body — the playbook itself */}
      {expanded && (
        <article className="mt-3 ml-7 bg-bg-primary border border-border-dim rounded p-4 prose prose-invert prose-sm max-w-none">
          <ReactMarkdown remarkPlugins={[remarkGfm]}>
            {skill.content}
          </ReactMarkdown>
        </article>
      )}
    </li>
  );
}

// ───────────────────────────────────────────────────────────────────────────
// Confirmation modal — forget is reversible by an admin, but it changes
// agent behaviour immediately, so we keep an explicit confirm step.
// ───────────────────────────────────────────────────────────────────────────

function ConfirmForgetModal({
  onCancel,
  onConfirm,
  busy,
}: {
  onCancel: () => void;
  onConfirm: () => Promise<void>;
  busy: boolean;
}) {
  const t = useTranslations("learningSkills");
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4"
      onClick={onCancel}
    >
      <div
        className="bg-bg-secondary border border-border-dim rounded-lg max-w-sm w-full p-5"
        onClick={(e) => e.stopPropagation()}
      >
        <h3 className="text-sm font-medium text-text-primary">
          {t("forgetConfirmTitle")}
        </h3>
        <p className="text-xs text-text-secondary mt-2">
          {t("forgetConfirmBody")}
        </p>
        <div className="mt-4 flex items-center justify-end gap-2">
          <button
            onClick={onCancel}
            disabled={busy}
            className="text-xs px-3 py-1.5 text-text-muted hover:text-text-primary rounded transition-colors disabled:opacity-50"
          >
            {t("cancel")}
          </button>
          <button
            onClick={onConfirm}
            disabled={busy}
            className="text-xs px-3 py-1.5 bg-red-500/20 text-red-300 hover:bg-red-500/30 border border-red-500/30 rounded transition-colors disabled:opacity-50 flex items-center gap-1.5"
          >
            {busy && <Loader2 className="w-3 h-3 animate-spin" />}
            {t("forgetConfirmAction")}
          </button>
        </div>
      </div>
    </div>
  );
}
