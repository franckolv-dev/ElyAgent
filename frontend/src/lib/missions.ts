/**
 * @project    ELY — Exactly Like You
 * @file       frontend/src/lib/missions.ts
 * @brief      Mission API client + TypeScript types
 *
 * @author     Franck OLLIVIER <contact@agent-ely.fr>
 * @copyright  Copyright (c) 2025-2026 Franck OLLIVIER
 * @license    MIT
 *            https://opensource.org/licenses/MIT
 */
import { authFetch } from "./auth";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export type MissionStatus =
  | "draft" | "planning" | "running" | "paused"
  | "completed" | "failed" | "aborted";

export type StepPhase = "plan" | "act" | "eval" | "replan" | "hitl_wait";

export interface Mission {
  id: string;
  title: string;
  goal: string;
  status: MissionStatus;
  priority: number;
  source: string;
  created_at: string;
  updated_at: string;
  started_at: string | null;
  completed_at: string | null;
  deadline: string | null;
  budget_tokens: number;
  budget_iterations: number;
  tokens_used: number;
  iterations_used: number;
  tick_interval_seconds: number | null;
  next_tick_at: string | null;
  autonomous: boolean;
  final_summary: string | null;
  failure_reason: string | null;
  /** Sprint 4c — présent = mission structurée (viewer liste). */
  spec_yaml?: string | null;
  /** J6 — mandat d'autonomie : pending_validation | active | paused_*. */
  autonomy_state?: string | null;
  /** J6 — mandat sérialisé (JSON : tools_allow, on_unforeseen, budgets…). */
  mandate_json?: string | null;
}

/** J6 — vue lecture seule du workspace d'une mission autonome. */
export interface MissionWorkspace {
  carnet: string | null;
  journal: Record<string, unknown>[];
  counters: {
    day: string;
    tool_actions: number;
    llm_calls: number;
    tool_ack: boolean;
    llm_ack: boolean;
  } | null;
}

export interface MissionStep {
  id: string;
  iteration: number;
  phase: StepPhase;
  thought: string | null;
  tool_name: string | null;
  tool_input: Record<string, unknown> | null;
  tool_output: string | null;
  evaluation: string | null;
  success: boolean | null;
  tokens_used: number;
  duration_ms: number;
  model_used: string | null;
  created_at: string;
}

export interface MissionPlan {
  id: string;
  version: number;
  plan_text: string;
  plan_json: { steps?: Array<{ id: string; description: string; status?: string; tool_hint?: string | null }>; estimated_iterations?: number } | null;
  reason_for_replan: string | null;
  created_at: string;
}

// ── Sprint 4c — missions structurées ────────────────────────────────────────

/** Un step de la spec (outline du viewer — tous les steps, même futurs). */
export interface SpecStepOutline {
  id: string;
  do: string;
  foreach: string | null;
  handler_cases: string[];
}

/** Statut d'exécution d'un item de step (✓/⏳/⏸/⊝/✗). */
export interface StepRun {
  step_id: string;
  item_index: number;
  item_value: string | null;
  status: "pending" | "running" | "done" | "skipped" | "waiting_user" | "failed";
  note: string | null;
  output: string | null;
  answer: string | null;
  attempts: number;
}

export interface MissionStructure {
  steps: SpecStepOutline[];
  runs: StepRun[];
}

export interface CreateMissionBody {
  title: string;
  goal: string;
  priority?: number;
  budget_tokens?: number;
  budget_iterations?: number;
  tick_interval_seconds?: number | null;
  deadline?: string | null;
  autonomous?: boolean;
  /** Sprint 4c — spec structurée YAML (optionnelle, validée serveur). */
  spec_yaml?: string | null;
}

/** Editable subset for PATCH — all optional, only sent fields change. */
export type UpdateMissionBody = Partial<CreateMissionBody>;

async function call<T>(path: string, opts: RequestInit = {}): Promise<T> {
  const res = await authFetch(`${API_URL}${path}`, {
    ...opts,
    headers: { "Content-Type": "application/json", ...(opts.headers as Record<string, string>) },
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({} as { detail?: unknown }));
    // FastAPI 422 validation errors return `detail` as an ARRAY of objects
    // (loc, msg, type) — JSON.stringify keeps them readable instead of
    // rendering "[object Object]" in the toast.
    const detail = body.detail;
    let msg: string;
    if (typeof detail === "string") {
      msg = detail;
    } else if (Array.isArray(detail)) {
      msg = detail
        .map((d) => (typeof d === "object" && d !== null && "msg" in d ? String((d as { msg: unknown }).msg) : JSON.stringify(d)))
        .join(" · ");
    } else if (detail) {
      msg = JSON.stringify(detail);
    } else {
      msg = `HTTP ${res.status}`;
    }
    throw new Error(msg);
  }
  // Some endpoints (abort, etc.) may return null body
  const text = await res.text();
  return text ? JSON.parse(text) : (null as unknown as T);
}

export const missionsApi = {
  list: (status?: MissionStatus): Promise<Mission[]> =>
    call(`/api/missions${status ? `?status_filter=${status}` : ""}`),
  get: (id: string): Promise<Mission> => call(`/api/missions/${id}`),
  create: (body: CreateMissionBody): Promise<Mission> =>
    call("/api/missions", { method: "POST", body: JSON.stringify(body) }),
  /** Edit a mission's params (goal, budgets, schedule) in place instead of
   *  delete+recreate. Backend rejects edits while running/planning (409). */
  update: (id: string, body: UpdateMissionBody): Promise<Mission> =>
    call(`/api/missions/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
  steps: (id: string): Promise<MissionStep[]> => call(`/api/missions/${id}/steps`),
  /** Sprint 4c J4 — outline de la spec + statuts par item (viewer liste). */
  structure: (id: string): Promise<MissionStructure> => call(`/api/missions/${id}/structure`),
  /** Sprint 4c J3 — répondre à une question ask_user : l'item repart, la
   *  mission reprend immédiatement. */
  answerStepRun: (id: string, stepId: string, itemIndex: number, answer: string): Promise<StepRun> =>
    call(`/api/missions/${id}/step-runs/${stepId}/${itemIndex}/answer`, {
      method: "POST",
      body: JSON.stringify({ answer }),
    }),
  plan: (id: string): Promise<MissionPlan | null> => call(`/api/missions/${id}/plan`),
  /** J6 — validation HUMAINE du mandat : pending_validation → active. */
  activate: (id: string): Promise<Mission> =>
    call(`/api/missions/${id}/activate`, { method: "POST" }),
  /** J6 — carnet de bord + journal + compteurs du jour (lecture seule). */
  workspace: (id: string): Promise<MissionWorkspace> =>
    call(`/api/missions/${id}/workspace`),
  start: (id: string): Promise<Mission> => call(`/api/missions/${id}/start`, { method: "POST" }),
  pause: (id: string): Promise<Mission> => call(`/api/missions/${id}/pause`, { method: "POST" }),
  abort: (id: string, reason = "User-requested abort"): Promise<Mission> =>
    call(`/api/missions/${id}/abort`, { method: "POST", body: JSON.stringify({ reason }) }),
  tick: (id: string): Promise<{ iteration: number | null; plan_version: number | null; done: boolean; final_summary: string | null; last_eval_success: boolean | null }> =>
    call(`/api/missions/${id}/tick`, { method: "POST" }),
  /** Reset a mission to draft so it can be started again (clears plan + steps by default). */
  restart: (id: string, opts?: { keep_history?: boolean; max_iterations?: number; max_tokens?: number }): Promise<Mission> =>
    call(`/api/missions/${id}/restart`, {
      method: "POST",
      body: JSON.stringify(opts ?? {}),
    }),
  /** Permanently delete a mission, its plan and its steps (also wipes LangGraph checkpoint). */
  remove: (id: string): Promise<void> =>
    call(`/api/missions/${id}`, { method: "DELETE" }),
};

// ── UI helpers ──────────────────────────────────────────────────────────────

export const STATUS_META: Record<MissionStatus, { label: string; color: string; emoji: string }> = {
  draft:     { label: "Brouillon", color: "text-text-muted bg-bg-secondary border-border-dim", emoji: "📝" },
  planning:  { label: "Planification", color: "text-amber-400 bg-amber-500/10 border-amber-500/20", emoji: "🧠" },
  running:   { label: "En cours", color: "text-cyber-cyan bg-cyber-cyan/10 border-cyber-cyan/20", emoji: "⚡" },
  paused:    { label: "En pause", color: "text-amber-400 bg-amber-500/10 border-amber-500/20", emoji: "⏸️" },
  completed: { label: "Terminée", color: "text-emerald-400 bg-emerald-500/10 border-emerald-500/20", emoji: "✅" },
  failed:    { label: "Échec", color: "text-red-400 bg-red-500/10 border-red-500/20", emoji: "❌" },
  aborted:   { label: "Abandonnée", color: "text-text-muted bg-bg-secondary border-border-dim", emoji: "🛑" },
};

export const PHASE_META: Record<StepPhase, { label: string; color: string }> = {
  plan:      { label: "Plan",     color: "text-purple-400" },
  act:       { label: "Action",   color: "text-cyber-cyan" },
  eval:      { label: "Eval",     color: "text-amber-400" },
  replan:    { label: "Replan",   color: "text-pink-400" },
  hitl_wait: { label: "HITL",     color: "text-orange-400" },
};

export function isTerminal(s: MissionStatus): boolean {
  return s === "completed" || s === "failed" || s === "aborted";
}
