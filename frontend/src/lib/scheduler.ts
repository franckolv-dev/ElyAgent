/**
 * @project    ELY — Exactly Like You
 * @file       frontend/src/lib/scheduler.ts
 * @brief      Scheduled-tasks API client + types. Comble le manque d'UI :
 *             les tâches cron créées par l'agent étaient invisibles et
 *             non-supprimables côté frontend (bug terrain 13/06).
 *
 * @author     Franck OLLIVIER <contact@agent-ely.fr>
 * @copyright  Copyright (c) 2025-2026 Franck OLLIVIER
 * @license    MIT
 *            https://opensource.org/licenses/MIT
 */
import { authFetch } from "./auth";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

// `silent` et `missed` étaient ÉMIS par le backend sans figurer ici : le
// rendu de /scheduled tombait sur un statut inconnu. `missed` = occurrence
// due mais trop ancienne pour la fenêtre de rattrapage — elle ne sera pas
// rejouée (06/08).
export type RunStatus = "running" | "success" | "error" | "silent" | "missed";

export interface ScheduledTask {
  id: string;
  name: string;
  prompt: string;
  cron_expression: string;
  channel: string;
  enabled: boolean;
  last_run_at: string | null;
  last_result: string | null;
  last_status: RunStatus | null;       // null = jamais exécutée
  last_run_started_at: string | null;
  // Cette tâche a-t-elle le DROIT de se taire ? Seule une tâche de veille.
  allow_silent: boolean;
  // Cette tâche lance une MISSION à l'heure dite (carnet, budgets, passages)
  // au lieu d'un tour de chat — pour les travaux longs (0036, 04/09).
  as_mission: boolean;
  created_at: string;
}

async function call<T>(path: string, opts: RequestInit = {}): Promise<T> {
  // Le router scheduler est monté sous /scheduler (PAS /api/scheduler).
  const res = await authFetch(`${API_URL}${path}`, {
    ...opts,
    headers: { "Content-Type": "application/json", ...(opts.headers as Record<string, string>) },
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({} as { detail?: unknown }));
    const detail = body.detail;
    let msg: string;
    if (typeof detail === "string") msg = detail;
    else if (Array.isArray(detail)) {
      msg = detail
        .map((d) => (typeof d === "object" && d !== null && "msg" in d ? String((d as { msg: unknown }).msg) : JSON.stringify(d)))
        .join(" · ");
    } else if (detail) msg = JSON.stringify(detail);
    else msg = `HTTP ${res.status}`;
    throw new Error(msg);
  }
  if (res.status === 204) return undefined as T;
  const text = await res.text();
  return (text ? JSON.parse(text) : undefined) as T;
}

export const schedulerApi = {
  /** List the current user's scheduled tasks (most recent first). */
  list: (): Promise<ScheduledTask[]> => call("/scheduler/"),

  /** C5 — create a task from the UI (until now only the agent created
   *  them via its tool). Used by the anticipation-suggestion flow: the
   *  USER clicks create, Ely never creates a task on its own. */
  create: (body: {
    name: string;
    prompt: string;
    cron_expression: string;
    channel?: string;
    as_mission?: boolean;
  }): Promise<ScheduledTask> =>
    call("/scheduler/", {
      method: "POST",
      body: JSON.stringify({ channel: "web", ...body }),
    }),

  /** Enable/disable a task without deleting it (cron is (un)registered server-side). */
  setEnabled: (id: string, enabled: boolean): Promise<ScheduledTask> =>
    call(`/scheduler/${id}`, { method: "PUT", body: JSON.stringify({ enabled }) }),

  /** Permanently delete a task — real DB delete + cron unschedule. */
  remove: (id: string): Promise<void> =>
    call(`/scheduler/${id}`, { method: "DELETE" }),

  /** Trigger a task immediately, out-of-band (result delivered via its channel). */
  runNow: (id: string): Promise<{ message: string }> =>
    call(`/scheduler/${id}/run`, { method: "POST" }),
};

// ── Helpers ───────────────────────────────────────────────────────────────

/** C5 — convert an anticipation cadence label ("daily@09:00" |
 *  "weekly:mon@09:00") into the 5-field cron the scheduler expects.
 *  Unknown shapes return null (the modal falls back to an empty field). */
export function cadenceToCron(cadence: string): string | null {
  const DOW: Record<string, number> = {
    sun: 0, mon: 1, tue: 2, wed: 3, thu: 4, fri: 5, sat: 6,
  };
  let m = cadence.match(/^daily@(\d{2}):(\d{2})$/);
  if (m) return `${Number(m[2])} ${Number(m[1])} * * *`;
  m = cadence.match(/^weekly:(\w{3})@(\d{2}):(\d{2})$/);
  if (m && m[1] in DOW) return `${Number(m[3])} ${Number(m[2])} * * ${DOW[m[1]]}`;
  return null;
}

/** Best-effort human label for a 5-field cron expression (common patterns). */
export function describeCron(cron: string): string {
  const parts = cron.trim().split(/\s+/);
  if (parts.length !== 5) return cron;
  const [min, hour, dom, mon, dow] = parts;
  const hhmm = (h: string, m: string) =>
    `${h.padStart(2, "0")}:${m.padStart(2, "0")}`;
  const DOW = ["dim", "lun", "mar", "mer", "jeu", "ven", "sam"];
  // Daily at fixed time
  if (dom === "*" && mon === "*" && dow === "*" && /^\d+$/.test(min) && /^\d+$/.test(hour))
    return `tous les jours à ${hhmm(hour, min)}`;
  // Weekdays
  if (dom === "*" && mon === "*" && dow === "1-5" && /^\d+$/.test(min) && /^\d+$/.test(hour))
    return `en semaine à ${hhmm(hour, min)}`;
  // Single weekday
  if (dom === "*" && mon === "*" && /^\d+$/.test(dow) && /^\d+$/.test(min) && /^\d+$/.test(hour))
    return `chaque ${DOW[Number(dow) % 7]}. à ${hhmm(hour, min)}`;
  return cron;
}
