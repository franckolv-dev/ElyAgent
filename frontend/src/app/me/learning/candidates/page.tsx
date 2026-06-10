"use client";
/**
 * @project    ELY — Exactly Like You
 * @file       frontend/src/app/me/learning/candidates/page.tsx
 *             (moved out of /admin/learning/* on 2026-06-04 — that path is a
 *              backend API namespace [learning_skills router prefix
 *              "/admin/learning"], and next.config rewrites /admin/* to the
 *              backend, so the page 404'd with {"detail":"Not Found"} whenever
 *              the build didn't win the afterFiles race. /me/* is frontend-owned.)
 * @brief      Sprint 4b Phase 4.a — admin HITL review of learned-skill
 *             candidates. The skill_creator loop emits playbooks in
 *             `candidate` status and, by design, never promotes them
 *             itself (a human must read the playbook and decide). Until
 *             this page existed there was no surface for that decision, so
 *             candidates sat inert forever. Backed by the admin endpoints
 *             `/admin/learning/skills/{candidates,promote,archive,restore}`.
 *
 *             Promoting a candidate flips it to `active`, which injects it
 *             into the agent's system prompt at the next turn — so this is
 *             a deliberate, auditable human gate.
 *
 * @author     Franck OLLIVIER <contact@agent-ely.fr>
 * @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
 * @license    Elastic License 2.0
 */

import { useCallback, useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import {
  Sparkles, Loader2, AlertCircle, RefreshCw, ChevronDown, ChevronRight,
  CheckCircle2, XCircle, Archive, RotateCcw, ShieldCheck, CheckCircle,
  Code2, FileText, Globe,
} from "lucide-react";

import { AdminGuard } from "@/components/layout/AuthGuard";
import { Sidebar } from "@/components/layout/Sidebar";
import { Header } from "@/components/layout/Header";
import { api, type LearnedSkillCandidate } from "@/lib/api";

// ── Status filters offered as chips ─────────────────────────────────────────
// `candidate` is the default (the promotion queue). The others let an admin
// audit what's live, dormant, retired or dead.
const FILTERS = ["candidate", "active", "stale", "archived", "rejected"] as const;
type Filter = (typeof FILTERS)[number];

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

function scoreBadgeClass(score: number): string {
  if (score >= 80) return "bg-emerald-500/10 text-emerald-300 border-emerald-500/30";
  if (score >= 60) return "bg-amber-500/10 text-amber-300 border-amber-500/30";
  return "bg-red-500/10 text-red-300 border-red-500/30";
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

// ── Which lifecycle actions are valid from a given status ───────────────────
// Mirrors `_ALLOWED_TRANSITIONS` in backend/app/routers/learning_skills.py.
type ActionKind = "promote" | "reject" | "archive" | "restore";

function actionsFor(status: string): ActionKind[] {
  switch (status) {
    case "candidate":
      return ["promote", "reject"];
    case "stale":
      return ["promote", "archive"];
    case "active":
      return ["archive"];
    case "archived":
      return ["restore"];
    default: // rejected — terminal
      return [];
  }
}

// Sprint 4b V2 J8 — a python_tool candidate is generated code, not a
// playbook: render its source + the 5-stage validation report so the human
// gate is informed, not a blind click.
const PYTHON_FORMAT = "python_tool";

type ValidationStage = { stage: string; ok: boolean; detail?: string };
type ValidationReportShape = {
  ok?: boolean;
  failed_stage?: string | null;
  stages?: ValidationStage[];
};

function parseValidationReport(raw: string): ValidationReportShape | null {
  try {
    const parsed = JSON.parse(raw || "{}");
    return parsed && typeof parsed === "object" ? parsed : null;
  } catch {
    return null;
  }
}

// Per-stage verdicts from the validation pipeline (ast → ruff → mypy →
// smoke → registration). Fail-fast, so a failed run lists only the stages
// that actually ran. Empty / unparseable → a plain "no report" note.
function ValidationReport({ raw }: { raw: string }) {
  const t = useTranslations("learningCandidates");
  const report = parseValidationReport(raw);
  const stages = report?.stages ?? [];

  if (!report || stages.length === 0) {
    return (
      <p className="mb-3 text-[11px] text-text-muted italic">
        {t("noValidation")}
      </p>
    );
  }

  return (
    <div className="mb-3 rounded border border-border-dim bg-bg-secondary p-3">
      <div className="flex items-center gap-2 mb-2">
        <ShieldCheck className="w-3.5 h-3.5 text-cyber-cyan" />
        <span className="text-[11px] font-medium text-text-secondary">
          {t("validationReport")}
        </span>
        <span
          className={`ml-auto text-[10px] font-mono ${
            report.ok ? "text-emerald-300" : "text-red-300"
          }`}
        >
          {report.ok
            ? t("validationPassed", { n: stages.length })
            : t("validationFailed", { stage: report.failed_stage ?? "?" })}
        </span>
      </div>
      <ul className="space-y-1">
        {stages.map((s) => (
          <li key={s.stage} className="flex items-start gap-2 text-[11px]">
            {s.ok ? (
              <CheckCircle2 className="w-3 h-3 text-emerald-400 mt-0.5 shrink-0" />
            ) : (
              <XCircle className="w-3 h-3 text-red-400 mt-0.5 shrink-0" />
            )}
            <code className="font-mono text-text-secondary w-24 shrink-0">{s.stage}</code>
            {s.detail && <span className="text-text-muted break-words">{s.detail}</span>}
          </li>
        ))}
      </ul>
    </div>
  );
}

// Sprint 4b V3 J8 — un candidat `io` déclare un PÉRIMÈTRE (domaines egress,
// libs, labels Vault) en plus de son code : promouvoir, c'est valider les
// deux. Ce panneau rend les trois listes en chips pour que la revue se fasse
// en un coup d'œil, sans lire le décorateur dans la source.
function IoDeclarationsPanel({ skill }: { skill: LearnedSkillCandidate }) {
  const t = useTranslations("learningCandidates");
  const chips = (
    items: string[] | null | undefined,
    tone: string,
  ) =>
    items && items.length > 0 ? (
      items.map((item) => (
        <code
          key={item}
          className={`px-1.5 py-0.5 text-[10px] font-mono rounded border ${tone}`}
        >
          {item}
        </code>
      ))
    ) : (
      <span className="text-[10px] text-text-muted italic">{t("ioNone")}</span>
    );

  return (
    <div className="mb-3 rounded border border-orange-500/30 bg-orange-500/5 p-3">
      <div className="flex items-center gap-2 mb-2">
        <Globe className="w-3.5 h-3.5 text-orange-300" />
        <span className="text-[11px] font-medium text-text-secondary">
          {t("ioPanelTitle")}
        </span>
      </div>
      <dl className="space-y-1.5 text-[11px]">
        <div className="flex items-start gap-2 flex-wrap">
          <dt className="text-text-muted w-28 shrink-0">{t("ioEgress")}</dt>
          <dd className="flex gap-1 flex-wrap">
            {chips(skill.v3_network_allow, "bg-orange-500/10 text-orange-200 border-orange-500/30")}
          </dd>
        </div>
        <div className="flex items-start gap-2 flex-wrap">
          <dt className="text-text-muted w-28 shrink-0">{t("ioDeps")}</dt>
          <dd className="flex gap-1 flex-wrap">
            {chips(skill.v3_requires, "bg-violet-500/10 text-violet-200 border-violet-500/30")}
          </dd>
        </div>
        <div className="flex items-start gap-2 flex-wrap">
          <dt className="text-text-muted w-28 shrink-0">{t("ioSecrets")}</dt>
          <dd className="flex gap-1 flex-wrap">
            {chips(skill.v3_requires_secrets, "bg-cyber-cyan/10 text-cyber-cyan border-cyber-cyan/30")}
          </dd>
        </div>
      </dl>
      <p className="mt-2 text-[10px] text-text-muted">{t("ioReviewHint")}</p>
    </div>
  );
}

export default function AdminLearningCandidatesPage() {
  const t = useTranslations("learningCandidates");

  const [filter, setFilter]   = useState<Filter>("candidate");
  const [rows, setRows]       = useState<LearnedSkillCandidate[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError]     = useState<string | null>(null);

  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [busyId, setBusyId]         = useState<string | null>(null);
  const [flash, setFlash]           = useState<{ kind: "ok" | "err"; text: string } | null>(null);

  const showFlash = (kind: "ok" | "err", text: string) => {
    setFlash({ kind, text });
    setTimeout(() => setFlash(null), 4000);
  };

  const fetchRows = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await api.adminLearningCandidates(filter);
      setRows(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : t("errorLoad"));
    } finally {
      setLoading(false);
    }
  }, [filter, t]);

  useEffect(() => {
    fetchRows();
  }, [fetchRows]);

  // Every action moves the row out of the current filter view, so we drop it
  // from local state on success rather than re-fetching (keeps it snappy).
  const runAction = async (skill: LearnedSkillCandidate, kind: ActionKind) => {
    if (busyId) return;
    setBusyId(skill.id);
    try {
      if (kind === "promote") await api.adminLearningPromote(skill.id);
      else if (kind === "restore") await api.adminLearningRestore(skill.id);
      else await api.adminLearningArchive(skill.id); // reject + archive both hit /archive
      setRows((cur) => cur.filter((r) => r.id !== skill.id));
      showFlash("ok", t(`flash_${kind}`, { name: skill.name }));
    } catch (e) {
      showFlash("err", e instanceof Error ? e.message : t("actionError"));
    } finally {
      setBusyId(null);
    }
  };

  return (
    <AdminGuard>
      <div className="flex flex-col h-screen overflow-hidden">
        <Header />
        <div className="flex flex-1 overflow-hidden">
          <Sidebar />
          <main
            className="flex-1 overflow-y-auto p-6 space-y-4"
            style={{ background: "var(--bg-app)" }}
          >
            {/* ── Header ──────────────────────────────────────────────── */}
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div className="flex items-center gap-3">
                <ShieldCheck className="w-5 h-5 text-cyber-cyan" />
                <h1 className="text-lg font-medium text-text-primary">
                  {t("title")}
                </h1>
                <span className="text-[11px] text-text-muted">
                  {t("subtitle")}
                </span>
              </div>

              <button
                onClick={fetchRows}
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

            {/* ── Admin gate note ────────────────────────────────────── */}
            <p className="text-[11px] text-text-muted bg-bg-secondary border border-border-dim rounded px-3 py-2">
              {t("adminNote")}
            </p>

            {/* ── Status filter chips ────────────────────────────────── */}
            <div className="flex flex-wrap items-center gap-1.5">
              {FILTERS.map((f) => (
                <button
                  key={f}
                  onClick={() => { setFilter(f); setExpandedId(null); }}
                  className={`px-2.5 py-1 text-[11px] font-mono rounded border transition-colors ${
                    filter === f
                      ? statusBadgeClass(f)
                      : "bg-bg-primary text-text-muted border-border-dim hover:text-text-secondary"
                  }`}
                >
                  {f}
                </button>
              ))}
            </div>

            {/* ── Flash feedback ─────────────────────────────────────── */}
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
            {!loading && !error && rows.length === 0 && (
              <div className="bg-bg-secondary border border-border-dim rounded-lg p-8 text-center">
                <Sparkles className="w-8 h-8 text-text-muted mx-auto mb-3" />
                <p className="text-sm text-text-secondary">
                  {filter === "candidate" ? t("emptyCandidate") : t("empty")}
                </p>
              </div>
            )}

            {/* ── List ──────────────────────────────────────────────── */}
            {!loading && !error && rows.length > 0 && (
              <section className="bg-bg-secondary border border-border-dim rounded-lg overflow-hidden">
                <header className="flex items-center gap-2 px-4 py-3 border-b border-border-dim">
                  <span className={`px-2 py-0.5 text-[10px] font-mono rounded border ${statusBadgeClass(filter)}`}>
                    {filter}
                  </span>
                  <span className="ml-auto text-[10px] text-text-muted">{rows.length}</span>
                </header>
                <ul className="divide-y divide-border-dim/50">
                  {rows.map((s) => (
                    <CandidateRow
                      key={s.id}
                      skill={s}
                      expanded={expandedId === s.id}
                      onToggleExpand={() =>
                        setExpandedId((cur) => (cur === s.id ? null : s.id))
                      }
                      onAction={(kind) => runAction(s, kind)}
                      busy={busyId === s.id}
                    />
                  ))}
                </ul>
              </section>
            )}
          </main>
        </div>
      </div>
    </AdminGuard>
  );
}

// ───────────────────────────────────────────────────────────────────────────
// Row — one candidate : header + metadata + lifecycle actions + body.
// ───────────────────────────────────────────────────────────────────────────

function CandidateRow({
  skill,
  expanded,
  onToggleExpand,
  onAction,
  busy,
}: {
  skill: LearnedSkillCandidate;
  expanded: boolean;
  onToggleExpand: () => void;
  onAction: (kind: ActionKind) => void;
  busy: boolean;
}) {
  const t = useTranslations("learningCandidates");
  const actions = actionsFor(skill.status);
  const isPython = skill.content_format === PYTHON_FORMAT;

  return (
    <li className="px-4 py-3">
      <div className="flex items-start gap-3">
        {/* Expand chevron */}
        <button
          onClick={onToggleExpand}
          className="mt-0.5 text-text-muted hover:text-cyber-cyan transition-colors"
          title={expanded ? t("collapse") : t(isPython ? "expandCode" : "expand")}
        >
          {expanded ? (
            <ChevronDown className="w-4 h-4" />
          ) : (
            <ChevronRight className="w-4 h-4" />
          )}
        </button>

        <div className="flex-1 min-w-0">
          {/* Top line : name + score */}
          <div className="flex items-center gap-2 flex-wrap">
            <code className="text-sm font-medium text-text-primary truncate">
              {skill.name}
            </code>
            <span
              className={`px-1.5 py-0.5 text-[10px] font-mono rounded border inline-flex items-center gap-1 ${
                isPython
                  ? "bg-violet-500/10 text-violet-300 border-violet-500/30"
                  : "bg-bg-primary text-text-muted border-border-dim"
              }`}
              title={isPython ? t("formatPythonHint") : t("formatPlaybookHint")}
            >
              {isPython ? <Code2 className="w-3 h-3" /> : <FileText className="w-3 h-3" />}
              {isPython ? t("formatPython") : t("formatPlaybook")}
            </span>
            {skill.tool_profile === "io" && (
              <span
                className="px-1.5 py-0.5 text-[10px] font-mono rounded border inline-flex items-center gap-1 bg-orange-500/10 text-orange-300 border-orange-500/30"
                title={t("ioBadgeHint")}
              >
                <Globe className="w-3 h-3" />
                {t("ioBadge")}
              </span>
            )}
            {skill.last_eval_score !== null ? (
              <span className={`px-1.5 py-0.5 text-[10px] font-mono rounded border ${scoreBadgeClass(skill.last_eval_score)}`}>
                {t("scoreLabel", { score: skill.last_eval_score })}
              </span>
            ) : (
              <span className="text-[10px] text-text-muted">{t("noScore")}</span>
            )}
          </div>

          {/* Description */}
          <p className="text-xs text-text-secondary mt-1 line-clamp-2">
            {skill.description}
          </p>

          {/* Metadata row */}
          <div className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-0.5 text-[10px] text-text-muted">
            <span>{t("iterationsLabel", { n: skill.iteration_count })}</span>
            <span>{t("createdLabel", { date: fmtDate(skill.created_at) })}</span>
            <span className="font-mono">{t("userLabel", { id: skill.user_id.slice(0, 8) })}</span>
          </div>

          {/* Rationale (why the loop wrote this) */}
          {skill.rationale && (
            <p className="mt-1.5 text-[11px] text-text-muted italic border-l-2 border-border-dim pl-2">
              <span className="not-italic text-text-secondary">{t("rationaleLabel")}: </span>
              {skill.rationale}
            </p>
          )}
        </div>

        {/* Actions */}
        <div className="flex items-center gap-1.5 shrink-0">
          {actions.length === 0 && (
            <span className="text-[10px] text-text-muted">{t("terminal")}</span>
          )}
          {actions.includes("promote") && (
            <button
              onClick={() => onAction("promote")}
              disabled={busy}
              className="flex items-center gap-1 px-2 py-1 text-[11px] rounded border border-emerald-500/30 text-emerald-300 hover:bg-emerald-500/10 transition-colors disabled:opacity-50"
              title={t("promoteHint")}
            >
              {busy ? <Loader2 className="w-3 h-3 animate-spin" /> : <CheckCircle2 className="w-3 h-3" />}
              {t("promote")}
            </button>
          )}
          {actions.includes("reject") && (
            <button
              onClick={() => onAction("reject")}
              disabled={busy}
              className="flex items-center gap-1 px-2 py-1 text-[11px] rounded border border-red-500/30 text-red-300 hover:bg-red-500/10 transition-colors disabled:opacity-50"
              title={t("rejectHint")}
            >
              {busy ? <Loader2 className="w-3 h-3 animate-spin" /> : <XCircle className="w-3 h-3" />}
              {t("reject")}
            </button>
          )}
          {actions.includes("archive") && (
            <button
              onClick={() => onAction("archive")}
              disabled={busy}
              className="flex items-center gap-1 px-2 py-1 text-[11px] rounded border border-border-dim text-text-muted hover:text-amber-300 hover:border-amber-500/30 transition-colors disabled:opacity-50"
              title={t("archiveHint")}
            >
              {busy ? <Loader2 className="w-3 h-3 animate-spin" /> : <Archive className="w-3 h-3" />}
              {t("archive")}
            </button>
          )}
          {actions.includes("restore") && (
            <button
              onClick={() => onAction("restore")}
              disabled={busy}
              className="flex items-center gap-1 px-2 py-1 text-[11px] rounded border border-cyber-cyan/30 text-cyber-cyan hover:bg-cyber-cyan/10 transition-colors disabled:opacity-50"
              title={t("restoreHint")}
            >
              {busy ? <Loader2 className="w-3 h-3 animate-spin" /> : <RotateCcw className="w-3 h-3" />}
              {t("restore")}
            </button>
          )}
        </div>
      </div>

      {/* Expanded body — playbook Markdown, OR generated Python source +
          validation report (Sprint 4b V2 J8). */}
      {expanded && (
        isPython ? (
          <div className="mt-3 ml-7">
            {skill.tool_profile === "io" && <IoDeclarationsPanel skill={skill} />}
            <ValidationReport raw={skill.validation_report_json} />
            <pre className="overflow-x-auto rounded bg-bg-primary border border-border-dim p-3 text-[11px] leading-relaxed">
              <code className="font-mono text-text-secondary whitespace-pre">
                {skill.content}
              </code>
            </pre>
          </div>
        ) : (
          <article className="mt-3 ml-7 bg-bg-primary border border-border-dim rounded p-4 prose prose-invert prose-sm max-w-none">
            <ReactMarkdown remarkPlugins={[remarkGfm]}>
              {skill.content}
            </ReactMarkdown>
          </article>
        )
      )}
    </li>
  );
}
