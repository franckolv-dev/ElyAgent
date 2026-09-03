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
 * @copyright  Copyright (c) 2025-2026 Franck OLLIVIER
 * @license    MIT
 */

import { useCallback, useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import {
  Sparkles, Loader2, AlertCircle, RefreshCw, ChevronDown, ChevronRight,
  CheckCircle2, XCircle, Archive, RotateCcw, ShieldCheck, CheckCircle,
  Code2, FileText, Globe, GraduationCap, ExternalLink, Plus, X, Download,
} from "lucide-react";

import { AdminGuard } from "@/components/layout/AuthGuard";
import { Sidebar } from "@/components/layout/Sidebar";
import { Header } from "@/components/layout/Header";
import {
  api,
  type GraduationDryRun,
  type GraduationReport,
  type LearnedSkillCandidate,
} from "@/lib/api";

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

// ── Sprint 4d V4 — panneau de graduation (python_tool ACTIF uniquement) ─────
// Trois temps : (1) les gates J1 en chips au dépliage, (2) un dry-run qui
// rejoue la revalidation + montre les fichiers qui sortiraient, (3) la
// livraison réelle — Ely ouvre la PR, l'humain la review et la merge.
function GraduationPanel({ skill }: { skill: LearnedSkillCandidate }) {
  const t = useTranslations("learningCandidates");
  const [report, setReport] = useState<GraduationReport | null>(null);
  const [dryRun, setDryRun] = useState<GraduationDryRun | null>(null);
  const [phase, setPhase] = useState<"idle" | "loading" | "dryrun" | "delivering">("idle");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setPhase("loading");
    api.adminLearningGraduationReport(skill.id)
      .then((r) => { if (!cancelled) { setReport(r); setPhase("idle"); } })
      .catch((e) => {
        if (!cancelled) {
          setError(e instanceof Error ? e.message : t("gradError"));
          setPhase("idle");
        }
      });
    return () => { cancelled = true; };
  }, [skill.id, t]);

  const runDryRun = async () => {
    setPhase("dryrun");
    setError(null);
    try {
      setDryRun(await api.adminLearningGraduate(skill.id, { dryRun: true }));
    } catch (e) {
      setError(e instanceof Error ? e.message : t("gradError"));
    } finally {
      setPhase("idle");
    }
  };

  const deliver = async () => {
    if (!window.confirm(t("gradConfirm", { name: skill.name }))) return;
    setPhase("delivering");
    setError(null);
    try {
      setDryRun(await api.adminLearningGraduate(skill.id, { dryRun: false }));
    } catch (e) {
      setError(e instanceof Error ? e.message : t("gradError"));
    } finally {
      setPhase("idle");
    }
  };

  const delivered = dryRun?.delivery;

  return (
    <div className="mb-3 rounded border border-violet-500/30 bg-violet-500/5 p-3">
      <div className="flex items-center gap-2 mb-2">
        <GraduationCap className="w-3.5 h-3.5 text-violet-300" />
        <span className="text-[11px] font-medium text-text-secondary">{t("gradTitle")}</span>
        {report && (
          <span className={`ml-auto text-[10px] font-mono ${report.eligible ? "text-emerald-300" : "text-text-muted"}`}>
            {report.eligible ? t("gradEligible") : t("gradNotEligible")}
          </span>
        )}
      </div>

      {phase === "loading" && (
        <p className="text-[11px] text-text-muted"><Loader2 className="w-3 h-3 animate-spin inline mr-1" />{t("gradLoading")}</p>
      )}

      {/* Gates J1 en chips */}
      {report && (
        <div className="flex flex-wrap gap-1 mb-2">
          {report.gates.map((g) => (
            <span
              key={g.key}
              title={`${g.label} — ${String(g.value)} / ${String(g.threshold)}`}
              className={`px-1.5 py-0.5 text-[10px] font-mono rounded border inline-flex items-center gap-1 ${
                g.ok
                  ? "bg-emerald-500/10 text-emerald-300 border-emerald-500/30"
                  : "bg-red-500/10 text-red-300 border-red-500/30"
              }`}
            >
              {g.ok ? <CheckCircle2 className="w-2.5 h-2.5" /> : <XCircle className="w-2.5 h-2.5" />}
              {g.key}
            </span>
          ))}
        </div>
      )}

      {/* Résultat du dry-run */}
      {dryRun && !delivered && (
        <div className="mb-2 space-y-1 text-[11px]">
          <p className={dryRun.revalidation.ok ? "text-emerald-300" : "text-red-300"}>
            {dryRun.revalidation.ok
              ? t("gradRevalidationOk")
              : t("gradRevalidationKo", { stage: dryRun.revalidation.failed_stage ?? "?" })}
          </p>
          {!dryRun.composition.ok && (
            <p className="text-red-300">{t("gradCompositionKo", { tools: dryRun.composition.missing.join(", ") })}</p>
          )}
          <div className="text-text-muted">
            {t("gradFiles")}
            <ul className="mt-0.5 space-y-0.5">
              {dryRun.files.map((f) => (
                <li key={f.path}><code className="font-mono text-[10px]">{f.path}</code></li>
              ))}
            </ul>
          </div>
        </div>
      )}

      {/* Livraison faite — le lien PR (ou l'export) */}
      {delivered && (
        <p className="mb-2 text-[11px] text-emerald-300">
          {delivered.status === "pr_created" && delivered.pr_url ? (
            <>
              {t("gradPrOpened")}{" "}
              <a
                href={delivered.pr_url}
                target="_blank"
                rel="noreferrer"
                className="underline inline-flex items-center gap-1 hover:text-emerald-200"
              >
                {delivered.pr_url.split("/").slice(-2).join("/")}
                <ExternalLink className="w-3 h-3" />
              </a>
            </>
          ) : (
            t("gradExported", { path: delivered.export_path ?? "?" })
          )}
        </p>
      )}

      {error && (
        <p className="mb-2 text-[11px] text-red-300 break-words">{error}</p>
      )}

      {/* Actions */}
      {!delivered && (
        <div className="flex items-center gap-2">
          <button
            onClick={runDryRun}
            disabled={phase !== "idle"}
            className="flex items-center gap-1 px-2 py-1 text-[11px] rounded border border-violet-500/30 text-violet-300 hover:bg-violet-500/10 transition-colors disabled:opacity-50"
            title={t("gradDryRunHint")}
          >
            {phase === "dryrun" ? <Loader2 className="w-3 h-3 animate-spin" /> : <ShieldCheck className="w-3 h-3" />}
            {t("gradDryRun")}
          </button>
          {dryRun?.ready && (
            <button
              onClick={deliver}
              disabled={phase !== "idle"}
              className="flex items-center gap-1 px-2 py-1 text-[11px] rounded border border-emerald-500/30 text-emerald-300 hover:bg-emerald-500/10 transition-colors disabled:opacity-50"
              title={t("gradDeliverHint")}
            >
              {phase === "delivering" ? <Loader2 className="w-3 h-3 animate-spin" /> : <GraduationCap className="w-3 h-3" />}
              {t("gradDeliver")}
            </button>
          )}
        </div>
      )}
      <p className="mt-2 text-[10px] text-text-muted">{t("gradHint")}</p>
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

  // Amorçage funnel — création d'un outil à la demande (admin).
  const [showCreate, setShowCreate]   = useState(false);
  const [createBusy, setCreateBusy]   = useState(false);
  const [taskDesc, setTaskDesc]       = useState("");
  const [smokeJson, setSmokeJson]     = useState("");
  const [toolProfile, setToolProfile] = useState<"pure" | "io">("pure");

  // J5-B — import a SKILL.md playbook from a URL (lands as a candidate).
  const [importUrl, setImportUrl]   = useState("");
  const [importBusy, setImportBusy] = useState(false);

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

  // J5-B — importer un playbook SKILL.md depuis une URL. Atterrit en
  // "candidate" pour revue (contenu externe non fiable avant promotion).
  const importSkill = async () => {
    if (importBusy) return;
    const url = importUrl.trim();
    if (!url) return;
    setImportBusy(true);
    try {
      const res = await api.adminLearningImportSkill(url);
      if (res.status === "imported") {
        showFlash("ok", t("importOk", { name: res.name ?? "skill" }));
        setImportUrl("");
        if (filter === "candidate") await fetchRows();
        else setFilter("candidate");  // useEffect re-fetch → le candidat apparaît
      } else if (res.status === "duplicate") {
        showFlash("err", t("importDuplicate", { name: res.name ?? "skill" }));
      } else {
        showFlash("err", t("importError"));
      }
    } catch (e) {
      showFlash("err", e instanceof Error ? e.message : t("importError"));
    } finally {
      setImportBusy(false);
    }
  };

  // Amorçage funnel — déclenche une génération tool-creator (le candidat
  // atterrit dans la file "candidate"). Un-clic, plus de docker exec / curl.
  const createTool = async () => {
    if (createBusy) return;
    const desc = taskDesc.trim();
    if (desc.length < 8) { showFlash("err", t("createErrShort")); return; }
    let smoke: Record<string, unknown> | undefined;
    if (smokeJson.trim()) {
      try {
        const parsed = JSON.parse(smokeJson);
        if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) {
          showFlash("err", t("createErrSmoke")); return;
        }
        smoke = parsed as Record<string, unknown>;
      } catch { showFlash("err", t("createErrSmoke")); return; }
    }
    setCreateBusy(true);
    try {
      const me = (await api.getMe()) as { id: string };
      const res = await api.adminLearningToolCreatorRun({
        task_description: desc, user_id: me.id,
        smoke_kwargs: smoke, profile: toolProfile,
      });
      if (res.status === "created") {
        showFlash("ok", t("createOk", { name: res.tool_name ?? "tool" }));
        setShowCreate(false); setTaskDesc(""); setSmokeJson("");
        if (filter === "candidate") await fetchRows();
        else setFilter("candidate");  // useEffect re-fetch → le candidat apparaît
      } else {
        showFlash("err", t("createFailed", { status: res.status }));
      }
    } catch (e) {
      showFlash("err", e instanceof Error ? e.message : t("actionError"));
    } finally {
      setCreateBusy(false);
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

              <div className="flex items-center gap-1.5">
                <button
                  onClick={() => setShowCreate(true)}
                  className="flex items-center gap-1 px-2.5 py-1.5 text-[11px] rounded border border-cyber-cyan/30 text-cyber-cyan hover:bg-cyber-cyan/10 transition-colors"
                  title={t("createHint")}
                >
                  <Plus className="w-3.5 h-3.5" />
                  {t("createButton")}
                </button>
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
            </div>

            {/* ── Import a SKILL.md playbook from a URL (J5-B) ────────── */}
            <div className="flex flex-wrap items-center gap-2">
              <input
                type="url"
                value={importUrl}
                onChange={(e) => setImportUrl(e.target.value)}
                onKeyDown={(e) => { if (e.key === "Enter") importSkill(); }}
                placeholder={t("importPlaceholder")}
                className="flex-1 min-w-[240px] bg-bg-secondary border border-border-dim rounded px-3 py-1.5 text-[12px] text-text-primary focus:outline-none focus:border-cyber-cyan"
              />
              <button
                onClick={importSkill}
                disabled={importBusy || !importUrl.trim()}
                className="flex items-center gap-1 px-2.5 py-1.5 text-[11px] rounded border border-cyber-cyan/30 text-cyber-cyan hover:bg-cyber-cyan/10 transition-colors disabled:opacity-50"
                title={t("importHint")}
              >
                {importBusy ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Download className="w-3.5 h-3.5" />}
                {t("importButton")}
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
      </div>

      {/* ── Modale « Créer un outil » (amorçage funnel) ──────────────── */}
      {showCreate && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
          <div className="bg-bg-secondary border border-border-dim rounded-lg max-w-2xl w-full p-5 space-y-3 max-h-[90vh] overflow-y-auto">
            <div className="flex items-center gap-2">
              <Plus className="w-5 h-5 text-cyber-cyan" />
              <h2 className="text-sm font-medium text-text-primary">{t("createTitle")}</h2>
              <button
                onClick={() => setShowCreate(false)}
                className="ml-auto p-1 text-text-muted hover:text-text-secondary"
                aria-label={t("cancel")}
              >
                <X className="w-4 h-4" />
              </button>
            </div>
            <p className="text-[11px] text-text-muted">{t("createBody")}</p>

            <label className="block text-[11px] text-text-secondary">
              {t("createDescLabel")}
              <textarea
                value={taskDesc}
                onChange={(e) => setTaskDesc(e.target.value)}
                rows={6}
                placeholder={t("createDescPlaceholder")}
                className="mt-1 w-full text-xs font-mono rounded bg-bg-primary border border-border-dim text-text-primary p-2 focus:border-cyber-cyan/40 outline-none"
              />
            </label>

            <label className="block text-[11px] text-text-secondary">
              {t("createSmokeLabel")}
              <textarea
                value={smokeJson}
                onChange={(e) => setSmokeJson(e.target.value)}
                rows={4}
                placeholder='{"n": 10}'
                className="mt-1 w-full text-xs font-mono rounded bg-bg-primary border border-border-dim text-text-primary p-2 focus:border-cyber-cyan/40 outline-none"
              />
            </label>

            <label className="block text-[11px] text-text-secondary">
              {t("createProfileLabel")}
              <select
                value={toolProfile}
                onChange={(e) => setToolProfile(e.target.value as "pure" | "io")}
                className="mt-1 w-full text-xs rounded bg-bg-primary border border-border-dim text-text-primary p-2 outline-none"
              >
                <option value="pure">{t("createProfilePure")}</option>
                <option value="io">{t("createProfileIo")}</option>
              </select>
            </label>

            <div className="flex items-center gap-2 justify-end pt-1">
              <button
                onClick={() => setShowCreate(false)}
                className="px-3 py-1.5 text-[11px] rounded border border-border-dim text-text-muted hover:text-text-secondary"
              >
                {t("cancel")}
              </button>
              <button
                onClick={createTool}
                disabled={createBusy || taskDesc.trim().length < 8}
                className="px-3 py-1.5 text-[11px] rounded border border-cyber-cyan/30 text-cyber-cyan hover:bg-cyber-cyan/10 flex items-center gap-1 disabled:opacity-50"
              >
                {createBusy ? <Loader2 className="w-3 h-3 animate-spin" /> : <CheckCircle2 className="w-3 h-3" />}
                {t("createSubmit")}
              </button>
            </div>
          </div>
        </div>
      )}
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
            {skill.status === "active" && <GraduationPanel skill={skill} />}
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
