"use client";
/**
 * @project    ELY — Exactly Like You
 * @file       frontend/src/app/me/learning/page.tsx
 * @brief      Sprint 3.7 V1.5 Jalon 7b — UI "Ce que sait ELY de moi" :
 *             interactive learning report. Reads `/api/me/learning-report`
 *             (JSON) and renders 5 sections + raw-markdown toggle.
 *
 * @author     Franck OLLIVIER <contact@agent-ely.fr>
 * @copyright  Copyright (c) 2025-2026 Franck OLLIVIER
 * @license    MIT
 * @version    1.5.0
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslations } from "next-intl";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import {
  Brain, Loader2, AlertCircle, RefreshCw, FileText, LayoutGrid,
  ShieldAlert, AlertTriangle, ClipboardCheck, BarChart3, User as UserIcon,
  Download,
} from "lucide-react";

import { AuthGuard } from "@/components/layout/AuthGuard";
import { Sidebar } from "@/components/layout/Sidebar";
import { Header } from "@/components/layout/Header";
import { api, type LearningReport } from "@/lib/api";

// ── Window options ─────────────────────────────────────────────────────────
const WINDOW_OPTIONS = ["7d", "30d", "90d"] as const;
type WindowOpt = (typeof WINDOW_OPTIONS)[number];

type ViewMode = "structured" | "markdown";

// ── Date helpers ───────────────────────────────────────────────────────────
function fmtDate(iso: string): string {
  try {
    return new Date(iso).toLocaleDateString("fr-FR", {
      day: "2-digit",
      month: "short",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return iso;
  }
}

export default function LearningPage() {
  const t = useTranslations("learning");
  const [window, setWindow]   = useState<WindowOpt>("30d");
  const [view, setView]       = useState<ViewMode>("structured");

  const [report, setReport]   = useState<LearningReport | null>(null);
  const [markdown, setMarkdown] = useState<string>("");
  const [loading, setLoading] = useState(true);
  const [error, setError]     = useState<string | null>(null);

  const fetchReport = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      if (view === "structured") {
        const data = await api.getLearningReportJson(window);
        setReport(data);
      } else {
        const md = await api.getLearningReportMarkdown(window);
        setMarkdown(md);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Erreur réseau");
    } finally {
      setLoading(false);
    }
  }, [window, view]);

  useEffect(() => {
    fetchReport();
  }, [fetchReport]);

  const downloadMarkdown = async () => {
    try {
      const md = await api.getLearningReportMarkdown(window);
      const blob = new Blob([md], { type: "text/markdown;charset=utf-8" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `ely-learning-report-${window}-${new Date()
        .toISOString()
        .slice(0, 10)}.md`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    } catch {
      // best-effort — error already surfaced if connection broken
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
                <Brain className="w-5 h-5 text-cyber-cyan" />
                <h1 className="text-lg font-medium text-text-primary">
                  {t("title")}
                </h1>
                <span className="text-[11px] text-text-muted">
                  {t("subtitle")}
                </span>
              </div>

              <div className="flex items-center gap-2">
                {/* Window tabs */}
                <div className="flex border border-border-dim rounded overflow-hidden">
                  {WINDOW_OPTIONS.map((w) => (
                    <button
                      key={w}
                      onClick={() => setWindow(w)}
                      className={`text-xs px-3 py-1.5 transition-all ${
                        window === w
                          ? "bg-cyber-cyan/10 text-cyber-cyan"
                          : "text-text-muted hover:text-text-secondary"
                      }`}
                    >
                      {t(`window_${w}`)}
                    </button>
                  ))}
                </div>

                {/* View toggle */}
                <div className="flex border border-border-dim rounded overflow-hidden">
                  <button
                    onClick={() => setView("structured")}
                    title={t("viewStructuredTooltip")}
                    className={`p-1.5 transition-all ${
                      view === "structured"
                        ? "bg-cyber-cyan/10 text-cyber-cyan"
                        : "text-text-muted hover:text-text-secondary"
                    }`}
                  >
                    <LayoutGrid className="w-3.5 h-3.5" />
                  </button>
                  <button
                    onClick={() => setView("markdown")}
                    title={t("viewMarkdownTooltip")}
                    className={`p-1.5 transition-all ${
                      view === "markdown"
                        ? "bg-cyber-cyan/10 text-cyber-cyan"
                        : "text-text-muted hover:text-text-secondary"
                    }`}
                  >
                    <FileText className="w-3.5 h-3.5" />
                  </button>
                </div>

                <button
                  onClick={fetchReport}
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

                <button
                  onClick={downloadMarkdown}
                  className="p-1.5 text-text-muted hover:text-cyber-cyan hover:bg-cyber-cyan/10 rounded transition-colors"
                  title={t("downloadTooltip")}
                >
                  <Download className="w-3.5 h-3.5" />
                </button>
              </div>
            </div>

            {/* Body */}
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

            {!loading && !error && view === "structured" && report && (
              <StructuredView report={report} />
            )}

            {!loading && !error && view === "markdown" && (
              <MarkdownView markdown={markdown} />
            )}

            {/* Footer note */}
            <p className="text-[10px] text-text-muted pt-2 border-t border-border-dim">
              {t("privacyNote")}
            </p>
          </main>
        </div>
        </div>
      </div>
    </AuthGuard>
  );
}

// ───────────────────────────────────────────────────────────────────────────
// Structured view — 5 cards
// ───────────────────────────────────────────────────────────────────────────

function StructuredView({ report }: { report: LearningReport }) {
  return (
    <div className="space-y-4">
      <PreferencesCard items={report.preferences} />
      <HitlRefusalsCard items={report.hitl_refusals} />
      <HallucinationsCard items={report.hallucinations} />
      <MissionCritiquesCard items={report.mission_critiques} />
      <TierPerformanceCard items={report.tier_performance} />
    </div>
  );
}

function CardShell({
  icon: Icon,
  title,
  count,
  children,
  tone = "default",
}: {
  icon: React.ComponentType<{ className?: string }>;
  title: string;
  count: number;
  children: React.ReactNode;
  tone?: "default" | "danger" | "warn";
}) {
  const toneClass =
    tone === "danger"
      ? "text-red-400"
      : tone === "warn"
        ? "text-amber-400"
        : "text-cyber-cyan";
  return (
    <section className="bg-bg-secondary border border-border-dim rounded-lg overflow-hidden">
      <header className="flex items-center gap-2 px-4 py-3 border-b border-border-dim">
        <Icon className={`w-4 h-4 ${toneClass}`} />
        <h2 className="text-sm font-medium text-text-primary">{title}</h2>
        <span className="ml-auto text-[10px] text-text-muted">{count}</span>
      </header>
      <div className="p-4">{children}</div>
    </section>
  );
}

// ── 1. Préférences ────────────────────────────────────────────────────────

function PreferencesCard({
  items,
}: {
  items: LearningReport["preferences"];
}) {
  const t = useTranslations("learning");
  return (
    <CardShell icon={UserIcon} title={t("sectionPrefs")} count={items.length}>
      {items.length === 0 ? (
        <p className="text-xs text-text-muted">{t("emptyPrefs")}</p>
      ) : (
        <ul className="space-y-1.5">
          {items.map((p) => (
            <li
              key={p.key + "::" + p.value}
              className="flex items-start gap-2 text-xs"
            >
              <span className="text-cyber-cyan/80 font-mono shrink-0">
                {p.key}
              </span>
              <span className="text-text-secondary">→</span>
              <span className="text-text-primary flex-1">{p.value}</span>
              {p.confidence < 0.95 && (
                <span className="text-[10px] text-text-muted shrink-0">
                  ({Math.round(p.confidence * 100)}%)
                </span>
              )}
            </li>
          ))}
        </ul>
      )}
    </CardShell>
  );
}

// ── 2. Refus HITL ─────────────────────────────────────────────────────────

function HitlRefusalsCard({
  items,
}: {
  items: LearningReport["hitl_refusals"];
}) {
  const t = useTranslations("learning");
  return (
    <CardShell
      icon={ShieldAlert}
      title={t("sectionHitl")}
      count={items.length}
      tone="warn"
    >
      {items.length === 0 ? (
        <p className="text-xs text-text-muted">{t("emptyHitl")}</p>
      ) : (
        <ul className="space-y-2">
          {items.map((r, idx) => (
            <li
              key={r.created_at + "::" + idx}
              className="text-xs border-l-2 border-amber-400/40 pl-3 py-0.5"
            >
              <div className="flex items-center gap-2 flex-wrap">
                <span className="text-text-muted">{fmtDate(r.created_at)}</span>
                <span className="px-1.5 py-0.5 rounded bg-amber-500/10 text-amber-400 text-[10px] font-mono">
                  {r.decision}
                </span>
                <code className="text-cyber-cyan/80 text-[11px]">
                  {r.tool_name}
                </code>
              </div>
              <p className="text-text-secondary mt-0.5 line-clamp-2">
                {r.action_description}
              </p>
              {r.reason && (
                <p className="text-text-muted mt-0.5 italic line-clamp-1">
                  « {r.reason} »
                </p>
              )}
            </li>
          ))}
        </ul>
      )}
    </CardShell>
  );
}

// ── 3. Hallucinations ─────────────────────────────────────────────────────

function HallucinationsCard({
  items,
}: {
  items: LearningReport["hallucinations"];
}) {
  const t = useTranslations("learning");
  return (
    <CardShell
      icon={AlertTriangle}
      title={t("sectionHallu")}
      count={items.length}
      tone="danger"
    >
      {items.length === 0 ? (
        <p className="text-xs text-emerald-300/80">{t("emptyHallu")}</p>
      ) : (
        <ul className="space-y-2">
          {items.map((h, idx) => (
            <li
              key={h.created_at + "::" + idx}
              className="text-xs border-l-2 border-red-500/40 pl-3 py-0.5"
            >
              <div className="flex items-center gap-2 flex-wrap">
                <span className="text-text-muted">{fmtDate(h.created_at)}</span>
                <code className="text-text-secondary text-[11px]">
                  {h.model_used}
                </code>
                {h.tier_llm && (
                  <span className="px-1.5 py-0.5 rounded bg-bg-primary text-text-muted text-[10px]">
                    tier {h.tier_llm}
                  </span>
                )}
              </div>
              {h.matched_patterns.length > 0 && (
                <div className="mt-1 flex flex-wrap gap-1">
                  {h.matched_patterns.map((p) => (
                    <span
                      key={p}
                      className="px-1.5 py-0.5 rounded bg-red-500/10 text-red-300 text-[10px] font-mono"
                    >
                      {p}
                    </span>
                  ))}
                </div>
              )}
              {h.original_response && (
                <p className="text-text-muted mt-1 italic line-clamp-2">
                  « {h.original_response} »
                </p>
              )}
            </li>
          ))}
        </ul>
      )}
    </CardShell>
  );
}

// ── 4. Mission critiques ──────────────────────────────────────────────────

function MissionCritiquesCard({
  items,
}: {
  items: LearningReport["mission_critiques"];
}) {
  const t = useTranslations("learning");
  return (
    <CardShell
      icon={ClipboardCheck}
      title={t("sectionCritiques")}
      count={items.length}
    >
      {items.length === 0 ? (
        <p className="text-xs text-text-muted">{t("emptyCritiques")}</p>
      ) : (
        <ul className="space-y-3">
          {items.map((c) => {
            const score = c.quality_score ?? 0;
            const scoreClass =
              score >= 70
                ? "text-emerald-300"
                : score >= 40
                  ? "text-amber-300"
                  : "text-red-300";
            return (
              <li
                key={c.mission_id}
                className="text-xs border-l-2 border-cyber-cyan/30 pl-3"
              >
                <div className="flex items-center gap-2 flex-wrap">
                  <span className="text-text-muted">
                    {fmtDate(c.created_at)}
                  </span>
                  <span className={`font-semibold ${scoreClass}`}>
                    {score}/100
                  </span>
                  <span className="px-1.5 py-0.5 rounded bg-bg-primary text-text-muted text-[10px] font-mono">
                    {c.status}
                  </span>
                </div>
                <p className="text-text-primary mt-0.5 line-clamp-1">
                  {c.goal}
                </p>
                <div className="mt-1 flex flex-wrap gap-1">
                  {!c.honest_completion && (
                    <Flag
                      tone="danger"
                      label={t("flagDishonest")}
                    />
                  )}
                  {c.wasted_effort && (
                    <Flag tone="warn" label={t("flagWasted")} />
                  )}
                  {c.user_should_have_been_warned && (
                    <Flag tone="warn" label={t("flagWarnUser")} />
                  )}
                </div>
                {c.main_issue && (
                  <p className="text-text-muted mt-1 italic line-clamp-2">
                    « {c.main_issue} »
                  </p>
                )}
                {c.critic_model && (
                  <p className="text-[10px] text-text-muted/60 mt-0.5">
                    {t("criticBy", { model: c.critic_model })}
                  </p>
                )}
              </li>
            );
          })}
        </ul>
      )}
    </CardShell>
  );
}

function Flag({
  tone,
  label,
}: {
  tone: "warn" | "danger";
  label: string;
}) {
  const cls =
    tone === "danger"
      ? "bg-red-500/10 text-red-300"
      : "bg-amber-500/10 text-amber-300";
  return (
    <span
      className={`px-1.5 py-0.5 rounded text-[10px] font-medium ${cls}`}
    >
      {label}
    </span>
  );
}

// ── 5. Tier performance ───────────────────────────────────────────────────

function TierPerformanceCard({
  items,
}: {
  items: LearningReport["tier_performance"];
}) {
  const t = useTranslations("learning");
  const totals = useMemo(() => {
    const hitl = items[0]?.hitl_refusals_total ?? 0;
    const hallu = items[0]?.hallucinations_total ?? 0;
    return { hitl, hallu };
  }, [items]);

  return (
    <CardShell
      icon={BarChart3}
      title={t("sectionTierPerf")}
      count={items.length}
    >
      {items.length === 0 ? (
        <p className="text-xs text-text-muted">{t("emptyTierPerf")}</p>
      ) : (
        <>
          <table className="w-full text-xs">
            <thead>
              <tr className="text-text-muted border-b border-border-dim">
                <th className="text-left py-1.5 font-normal">
                  {t("colModel")}
                </th>
                <th className="text-right py-1.5 font-normal">
                  {t("colMessages")}
                </th>
                <th className="text-right py-1.5 font-normal">
                  {t("colFeedback")}
                </th>
              </tr>
            </thead>
            <tbody>
              {items.map((row) => (
                <tr
                  key={row.label}
                  className="border-b border-border-dim/50 last:border-0"
                >
                  <td className="py-1.5">
                    <code className="text-cyber-cyan/80 text-[11px]">
                      {row.label}
                    </code>
                  </td>
                  <td className="py-1.5 text-right text-text-secondary">
                    {row.messages}
                  </td>
                  <td className="py-1.5 text-right text-text-secondary">
                    {row.feedback_count > 0
                      ? `${row.feedback_mean >= 0 ? "+" : ""}${row.feedback_mean.toFixed(
                          2,
                        )} (${row.feedback_count})`
                      : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="text-[11px] text-text-muted mt-3 pt-2 border-t border-border-dim">
            {t("totalsLine", {
              hitl: totals.hitl,
              hallu: totals.hallu,
            })}
          </p>
        </>
      )}
    </CardShell>
  );
}

// ───────────────────────────────────────────────────────────────────────────
// Markdown view — raw renderer for the same payload, useful for download
// ───────────────────────────────────────────────────────────────────────────

function MarkdownView({ markdown }: { markdown: string }) {
  return (
    <article className="bg-bg-secondary border border-border-dim rounded-lg p-6 prose prose-invert prose-sm max-w-none">
      <ReactMarkdown remarkPlugins={[remarkGfm]}>{markdown}</ReactMarkdown>
    </article>
  );
}
