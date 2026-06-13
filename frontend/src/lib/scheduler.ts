/**
 * @project    ELY — Exactly Like You
 * @file       frontend/src/lib/scheduler.ts
 * @brief      Scheduled-tasks API client + types. Comble le manque d'UI :
 *             les tâches cron créées par l'agent étaient invisibles et
 *             non-supprimables côté frontend (bug terrain 13/06).
 *
 * @author     Franck OLLIVIER <contact@agent-ely.fr>
 * @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
 * @license    Elastic License 2.0
 */
import { authFetch } from "./auth";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export interface ScheduledTask {
  id: string;
  name: string;
  prompt: string;
  cron_expression: string;
  channel: string;
  enabled: boolean;
  last_run_at: string | null;
  last_result: string | null;
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
