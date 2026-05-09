/**
 * @project    ELY — Exactly Like You
 * @file       frontend/src/lib/api.ts
 * @brief      API client — typed HTTP wrappers for backend endpoints
 *
 * @author     Franck OLLIVIER <contact@agent-ely.fr>
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

  /** Update one or more user preferences (currently: language).
   *  Best-effort — caller should swallow errors so UI isn't blocked. */
  updateUserPreferences: (prefs: { language?: "fr" | "en" }) =>
    fetchAPI("/auth/me/preferences", {
      method: "PATCH",
      body: JSON.stringify(prefs),
    }),

  getHosts: () => fetchAPI("/hosts/"),

  // ── Google multi-account (Phase 3) ─────────────────────────────────────
  // The google router is mounted under /api in main.py, so all paths must
  // start with /api/google (matching the existing /api/google/auth-url usage
  // in settings/page.tsx — keep consistency).
  /** List every Google account linked to the current user. */
  listGoogleAccounts: () =>
    fetchAPI("/api/google/accounts") as Promise<{
      accounts: Array<{ id: string; alias: string; email: string; is_default: boolean; created_at: string | null }>;
    }>,

  /** Whether the global Google OAuth app credentials are configured (no auth). */
  getGoogleAppConfigStatus: () =>
    fetchAPI("/api/google/app-config-status") as Promise<{ configured: boolean }>,

  /** Admin only — save the Google OAuth app credentials (used by the wizard). */
  saveGoogleAppConfig: (client_id: string, client_secret: string) =>
    fetchAPI("/api/google/app-config", {
      method: "POST",
      body: JSON.stringify({ client_id, client_secret }),
    }) as Promise<{ configured: boolean }>,

  /** Open the Google OAuth consent flow for a NEW account with the given alias. */
  getGoogleAuthUrl: (alias: string) =>
    fetchAPI(`/api/google/auth-url?alias=${encodeURIComponent(alias)}`) as Promise<{ url: string }>,

  /** Promote one Google account to the default (mirrors into User.google_credentials). */
  setGoogleDefault: (account_id: string) =>
    fetchAPI("/api/google/accounts/default", {
      method: "POST",
      body: JSON.stringify({ account_id }),
    }),

  /** Rename a Google account's alias. */
  renameGoogleAccount: (account_id: string, alias: string) =>
    fetchAPI(`/api/google/accounts/${account_id}`, {
      method: "PATCH",
      body: JSON.stringify({ alias }),
    }),

  /** Remove a single Google account (auto-promotes the next-oldest if it was default). */
  deleteGoogleAccount: (account_id: string) =>
    fetchAPI(`/api/google/accounts/${account_id}`, { method: "DELETE" }),

  // ── Watched folders (RAG auto-indexing) ─────────────────────────────────
  listWatchedFolders: () =>
    fetchAPI("/api/knowledge/watched-folders") as Promise<{
      folders: Array<{
        id: string;
        path: string;
        recursive: boolean;
        enabled: boolean;
        include_extensions: string;
        exclude_paths: string;
        last_scan_at: string | null;
        last_scan_status: string;
        last_scan_message: string;
        files_indexed: number;
        created_at: string;
      }>;
    }>,

  createWatchedFolder: (body: {
    path: string;
    recursive?: boolean;
    include_extensions?: string;
    exclude_paths?: string;
  }) =>
    fetchAPI("/api/knowledge/watched-folders", {
      method: "POST",
      body: JSON.stringify(body),
    }),

  updateWatchedFolder: (
    folder_id: string,
    body: {
      enabled?: boolean;
      recursive?: boolean;
      include_extensions?: string;
      exclude_paths?: string;
    },
  ) =>
    fetchAPI(`/api/knowledge/watched-folders/${folder_id}`, {
      method: "PATCH",
      body: JSON.stringify(body),
    }),

  deleteWatchedFolder: (folder_id: string) =>
    fetchAPI(`/api/knowledge/watched-folders/${folder_id}`, { method: "DELETE" }),

  scanWatchedFolderNow: (folder_id: string) =>
    fetchAPI(`/api/knowledge/watched-folders/${folder_id}/scan`, {
      method: "POST",
    }) as Promise<{
      indexed: number;
      skipped: number;
      errors: number;
      status: string;
      message: string;
    }>,

  // ── HITL preferences ─────────────────────────────────────────────────────
  listHitlPreferences: () =>
    fetchAPI("/api/hitl/preferences") as Promise<Array<{
      tool_name: string;
      requires_confirmation: boolean;
      locked: boolean;
      description: string | null;
    }>>,
  updateHitlPreference: (tool_name: string, requires_confirmation: boolean) =>
    fetchAPI("/api/hitl/preferences", {
      method: "PATCH",
      body: JSON.stringify({ tool_name, requires_confirmation }),
    }),

  // ── HITL preferred channel (fix #18 — May 2026) ──────────────────────────
  getHitlChannel: () =>
    fetchAPI("/api/hitl/channel") as Promise<{
      preferred_channel: string;
      available_channels: Array<{
        value: string;
        label: string;
        available: boolean;
        icon: string;
      }>;
    }>,
  updateHitlChannel: (preferred_channel: string) =>
    fetchAPI("/api/hitl/channel", {
      method: "PATCH",
      body: JSON.stringify({ preferred_channel }),
    }) as Promise<{
      preferred_channel: string;
      available_channels: Array<{
        value: string;
        label: string;
        available: boolean;
        icon: string;
      }>;
    }>,

  // ── Onboarding (conversational) ──────────────────────────────────────────
  getOnboardingStatus: () =>
    fetchAPI("/api/onboarding/status") as Promise<{
      completed: boolean;
      skipped: boolean;
      step: number;
      total: number;
      skip_count: number;
      should_show: boolean;
      completed_at: string | null;
      skipped_at: string | null;
    }>,
  getNextOnboardingQuestion: () =>
    fetchAPI("/api/onboarding/next-question") as Promise<{
      done: boolean;
      question: {
        id: string;
        text: string;
        placeholder: string;
        step: number;
        total: number;
        skippable: boolean;
      } | null;
    }>,
  submitOnboardingAnswer: (question_id: string, answer: string) =>
    fetchAPI("/api/onboarding/answer", {
      method: "POST",
      body: JSON.stringify({ question_id, answer }),
    }),
  skipOnboarding: () =>
    fetchAPI("/api/onboarding/skip", { method: "POST" }),
  restartOnboarding: () =>
    fetchAPI("/api/onboarding/restart", { method: "POST" }),

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

  // HITL — pending approval requests for the bell component
  hitlPending: () =>
    fetchAPI("/api/hitl/pending") as Promise<
      Array<{ action_id: string; description: string; created_at: string }>
    >,

  hitlResolve: (actionId: string, decision: "allow" | "deny" | "ban", reason?: string) =>
    fetchAPI(`/api/validation/${actionId}/${decision}`, {
      method: "POST",
      body: JSON.stringify({ reason: reason ?? null }),
    }),

  // ── Voice / TTS preferences ─────────────────────────────────────────────
  /** Get the current user's voice preferences (default: tts_auto_enabled=true). */
  voicePrefsGet: () =>
    fetchAPI("/api/preferences/voice") as Promise<{ tts_auto_enabled: boolean }>,

  /** Update one or more voice preferences. PATCH semantics — pass only the
   * fields you want to change. Returns the post-update state. */
  voicePrefsPatch: (patch: { tts_auto_enabled?: boolean }) =>
    fetchAPI("/api/preferences/voice", {
      method: "PATCH",
      body: JSON.stringify(patch),
    }) as Promise<{ tts_auto_enabled: boolean }>,

  // ── Licence enforcement (Phase 1) ────────────────────────────────────────
  /** Current licence state — drives the LicenceSection panel and global banner. */
  licenceStatus: () =>
    fetchAPI("/api/licence/status") as Promise<{
      tier: "free" | "pro" | "business" | "enterprise" | null;
      max_users: number | null;
      current_users: number;
      customer_label: string | null;
      valid_until: string | null;
      days_remaining: number | null;
      is_demo_expired: boolean;
      is_provisioned: boolean;
      consent_personal_use: boolean;
      activated_at: string | null;
    }>,

  /** Admin only — provision the free tier (max 4 users). Requires consent=true. */
  activateFree: (consent: boolean) =>
    fetchAPI("/api/licence/activate-free", {
      method: "POST",
      body: JSON.stringify({ consent }),
    }),

  /** Admin only — activate a paid tier with a licence key (raw string in Phase 1). */
  activatePaid: (tier: "pro" | "business" | "enterprise", licence_key: string, customer_label: string) =>
    fetchAPI("/api/licence/activate-paid", {
      method: "POST",
      body: JSON.stringify({ tier, licence_key, customer_label }),
    }),
};
