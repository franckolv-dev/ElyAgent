/**
 * @project    ELY — Exactly Like You
 * @file       frontend/src/lib/api.ts
 * @brief      API client — typed HTTP wrappers for backend endpoints
 *
 * @author     Franck OLLIVIER <franck.olv@gmail.com>
 * @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
 * @license    PolyForm Strict License 1.0.0
 *             https://polyformproject.org/licenses/strict/1.0.0/
 * @version    1.1.0
 * @link       https://github.com/franckolv-dev/PhysicalAgent
 *
 * RÉSUMÉ DES CONDITIONS :
 *   - AUTORISÉ : Utilisation personnelle, éducative et tests privés.
 *   - INTERDIT : Toute utilisation commerciale sans accord préalable.
 *   - INTERDIT : Redistribution de versions modifiées de ce code.
 */
import { authFetch } from "./auth";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

async function fetchAPI(path: string, options: RequestInit = {}) {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(options.headers as Record<string, string>),
  };

  // authFetch adds Authorization header and retries once after token refresh
  const res = await authFetch(`${API_URL}${path}`, { ...options, headers });

  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail || `API error: ${res.status}`);
  }

  return res.json();
}

export const api = {
  login: (username: string, password: string) =>
    fetchAPI("/auth/login", {
      method: "POST",
      body: JSON.stringify({ username, password }),
    }),

  register: (username: string, email: string, password: string) =>
    fetchAPI("/auth/register", {
      method: "POST",
      body: JSON.stringify({ username, email, password }),
    }),

  getMe: () => fetchAPI("/auth/me"),

  getHosts: () => fetchAPI("/hosts/"),

  getUsers: () => fetchAPI("/admin/users"),

  getAuditLogs: (limit = 50) => fetchAPI(`/admin/audit?limit=${limit}`),

  /** Submit thumbs up / down feedback on an assistant response. */
  submitFeedback: (params: {
    conversation_id: string;
    user_message: string;
    rating: 1 | -1;
    model_used?: string;
    routing_score?: number;
  }) =>
    fetchAPI("/api/feedback", {
      method: "POST",
      body: JSON.stringify(params),
    }),

  getConversations: (params?: { limit?: number; offset?: number; q?: string }) => {
    const sp = new URLSearchParams();
    if (params?.limit) sp.set("limit", String(params.limit));
    if (params?.offset) sp.set("offset", String(params.offset));
    if (params?.q) sp.set("q", params.q);
    return fetchAPI(`/api/conversations?${sp}`);
  },

  getConversationMessages: (id: string) =>
    fetchAPI(`/api/conversations/${id}/messages`),

  renameConversation: (id: string, title: string) =>
    fetchAPI(`/api/conversations/${id}`, {
      method: "PUT",
      body: JSON.stringify({ title }),
    }),

  deleteConversation: (id: string) =>
    fetchAPI(`/api/conversations/${id}`, { method: "DELETE" }),

  exportConversation: (id: string) =>
    fetchAPI(`/api/conversations/${id}/export`, { method: "POST" }),

  // Arena — blind LLM comparison + ELO leaderboard
  arenaListModels: () => fetchAPI("/api/arena/models"),

  arenaCreateMatch: (prompt: string, modelA?: string, modelB?: string) =>
    fetchAPI("/api/arena/match", {
      method: "POST",
      body: JSON.stringify({ prompt, model_a: modelA, model_b: modelB }),
    }),

  arenaVote: (matchId: string, vote: "a" | "b" | "tie" | "both_bad") =>
    fetchAPI("/api/arena/vote", {
      method: "POST",
      body: JSON.stringify({ match_id: matchId, vote }),
    }),

  arenaLeaderboard: () => fetchAPI("/api/arena/leaderboard"),

  arenaHistory: (limit = 20) => fetchAPI(`/api/arena/history?limit=${limit}`),
};
