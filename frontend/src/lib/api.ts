/**
 * @project    ELY — Exactly Like You
 * @file       frontend/src/lib/api.ts
 * @brief      API client — typed HTTP wrappers for backend endpoints
 *
 * @author     Franck OLLIVIER <contact@agent-ely.fr>
 * @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
 * @license    Elastic License 2.0
 *            https://www.elastic.co/licensing/elastic-license
 * @version    1.1.0
 * @link       https://github.com/franckolv-dev/PhysicalAgent
 *
 * RÉSUMÉ DES CONDITIONS :
 *   - AUTORISÉ : Usage personnel et professionnel interne (gratuit).
 *   - AUTORISÉ : Modification et redistribution avec attribution.
 *   - INTERDIT : Revente comme SaaS / service managé à des tiers.
 *   - INTERDIT : Suppression des notices de copyright ou de licence.
 */
import { authFetch } from "./auth";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

/** Authenticated fetch — adds Bearer token, retries once after token refresh. */
async function fetchAPI(path: string, options: RequestInit = {}) {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(options.headers as Record<string, string>),
  };

  const res = await authFetch(`${API_URL}${path}`, { ...options, headers });

  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail || `API error: ${res.status}`);
  }

  return res.json();
}

/**
 * Public (unauthenticated) fetch — plain fetch, no Bearer token, no token refresh.
 * Used for /auth/login and /auth/register so that a wrong-password 401 is returned
 * as-is to the caller instead of being intercepted by authFetch and rewritten as
 * "Session expirée".
 */
async function fetchPublic(path: string, options: RequestInit = {}) {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(options.headers as Record<string, string>),
  };

  const res = await fetch(`${API_URL}${path}`, { ...options, headers, credentials: "include" });

  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail || `API error: ${res.status}`);
  }

  return res.json();
}

export const api = {
  login: (username: string, password: string) =>
    fetchPublic("/auth/login", {
      method: "POST",
      body: JSON.stringify({ username, password }),
    }),

  register: (username: string, email: string, password: string) =>
    fetchPublic("/auth/register", {
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

  hitlResolve: (
    actionId: string,
    decision: "allow" | "allow_always" | "deny" | "ban",
    reason?: string,
  ) =>
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

  // ── Licence (Elastic License v2 — info only since 2026-05-28 pivot) ──────
  /** Static licence-info payload. Replaces the old tier-aware status. */
  licenceStatus: () =>
    fetchAPI("/api/licence/status") as Promise<{
      license: string;       // always "elastic-license-v2"
      name: string;          // "Elastic License v2"
      url: string;           // canonical text
      summary_url: string;   // agent-ely.fr/pricing.html
      free_for: string[];
      forbidden: string[];
    }>,

  // ── Browser-extension long-lived tokens (Sprint 0.5) ────────────────────
  extensionTokensList: () =>
    fetchAPI("/api/extension/tokens"),

  /** Returns the plaintext token ONCE — caller must show + let the user copy it. */
  extensionTokenCreate: (name: string) =>
    fetchAPI("/api/extension/tokens", {
      method: "POST",
      body: JSON.stringify({ name }),
    }),

  extensionTokenRevoke: (id: string) =>
    fetchAPI(`/api/extension/tokens/${id}`, { method: "DELETE" }),

  // ── Learning report (Sprint 3.7 V1.5 §7) ────────────────────────────────
  /** Fetch the structured learning report — what ELY has learned about the
   *  current user + how it has performed over `window` (7d, 30d, 90d, 24h). */
  getLearningReportJson: (window: string) =>
    fetchAPI(`/api/me/learning-report?window=${encodeURIComponent(window)}&format=json`) as Promise<LearningReport>,

  /** Same endpoint, markdown variant — useful for a "raw" view + download. */
  getLearningReportMarkdown: async (window: string): Promise<string> => {
    const res = await authFetch(
      `${API_URL}/api/me/learning-report?window=${encodeURIComponent(window)}&format=markdown`,
      { headers: { Accept: "text/markdown" } },
    );
    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      throw new Error(body.detail || `API error: ${res.status}`);
    }
    return res.text();
  },

  // ── User State Vector (Sprint 3 Jalon 3) ────────────────────────────────
  /** Read the current user state. Always returns the full shape with
   *  defaults filled in. */
  getUserState: () =>
    fetchAPI("/api/me/state?format=json") as Promise<UserStateResponse>,

  /** Trigger a synchronous MAINTENANCE-LLM refresh on the user's most
   *  recent conversation. The backend invalidates the frozen-memory
   *  snapshot so the next agent turn sees the new state. */
  recomputeUserState: () =>
    fetchAPI("/api/me/state/recompute", { method: "POST" }) as Promise<
      UserStateResponse & {
        refreshed: boolean;
        reason?: string;
        source_conversation_id?: string;
      }
    >,

  // ── MCP servers (Sprint 4a J2 — admin only) ─────────────────────────────
  mcpServersList: () =>
    fetchAPI("/admin/mcp/servers") as Promise<MCPServerOut[]>,

  mcpServerCreate: (body: MCPServerCreateBody) =>
    fetchAPI("/admin/mcp/servers", {
      method: "POST",
      body: JSON.stringify(body),
    }) as Promise<MCPServerOut>,

  mcpServerUpdate: (id: string, body: Partial<MCPServerCreateBody>) =>
    fetchAPI(`/admin/mcp/servers/${id}`, {
      method: "PUT",
      body: JSON.stringify(body),
    }) as Promise<MCPServerOut>,

  mcpServerDelete: (id: string) =>
    fetchAPI(`/admin/mcp/servers/${id}`, { method: "DELETE" }),

  mcpServerReload: (id: string) =>
    fetchAPI(`/admin/mcp/servers/${id}/reload`, { method: "POST" }) as Promise<{
      status: string;
      tools: string[];
    }>,

  // ── My learned skills (Sprint 4b Phase 5.b) ─────────────────────────────
  /** List every LearnedSkill the caller owns, across all statuses. The
   *  backend orders by status then use_count so the UI can render the
   *  list as-is (most relevant first). */
  myLearningSkillsList: () =>
    fetchAPI("/api/me/learning-skills") as Promise<MeLearnedSkill[]>,

  /** Toggle the `pinned` flag on one of the caller's skills. A pinned
   *  skill bypasses the auto-curator so it never drifts to stale /
   *  archived even when unused for months. */
  myLearningSkillPin: (id: string, pinned: boolean) =>
    fetchAPI(`/api/me/learning-skills/${id}/pin`, {
      method: "POST",
      body: JSON.stringify({ pinned }),
    }) as Promise<MeLearnedSkill>,

  /** "Forget" the skill — flips status to `archived`, hidden from the
   *  prompt injection layer. Reversible by an admin (no permanent
   *  delete from the user surface). No-op on already-archived rows. */
  myLearningSkillForget: (id: string) =>
    fetchAPI(`/api/me/learning-skills/${id}/forget`, {
      method: "POST",
    }) as Promise<MeLearnedSkill>,
};

// ─────────────────────────────────────────────────────────────────────────
// MCP servers (Sprint 4a J2)
// ─────────────────────────────────────────────────────────────────────────

export interface MCPServerOut {
  id: string;
  name: string;
  slug: string;
  transport: "stdio" | "sse";
  command: string | null;
  url: string | null;
  env_json: string | null;
  description: string | null;
  enabled: boolean;
  /** Filled by the backend from the live skill registry — null when the
   *  server is disabled or has failed to load. */
  tool_count: number | null;
  tool_names: string[] | null;
}

export interface MCPServerCreateBody {
  name: string;
  slug: string;
  transport: "stdio" | "sse";
  command?: string | null;
  url?: string | null;
  env_json?: string | null;
  description?: string | null;
  enabled?: boolean;
}

// ─────────────────────────────────────────────────────────────────────────
// Learning report — typed payload (Sprint 3.7 V1.5)
// ─────────────────────────────────────────────────────────────────────────

export interface LearningPreference {
  key: string;
  value: string;
  confidence: number;
  source_count: number;
  last_seen: string | null;
}

export interface LearningHitlRefusal {
  tool_name: string;
  action_description: string;
  decision: string;
  reason: string | null;
  created_at: string;
}

export interface LearningHallucination {
  model_used: string;
  tier_llm: string | null;
  reason: string | null;
  matched_patterns: string[];
  original_response: string;
  created_at: string;
}

export interface LearningMissionCritique {
  mission_id: string;
  goal: string;
  status: string;
  quality_score: number | null;
  honest_completion: boolean;
  wasted_effort: boolean;
  user_should_have_been_warned: boolean;
  main_issue: string | null;
  critic_model: string | null;
  created_at: string;
}

export interface LearningTierRow {
  label: string;
  messages: number;
  hitl_refusals_total: number;
  hallucinations_total: number;
  feedback_count: number;
  feedback_mean: number;
}

export interface LearningReport {
  preferences: LearningPreference[];
  hitl_refusals: LearningHitlRefusal[];
  hallucinations: LearningHallucination[];
  mission_critiques: LearningMissionCritique[];
  tier_performance: LearningTierRow[];
  window: string;
  since: string;
  generated_at: string;
}

// ─────────────────────────────────────────────────────────────────────────
// User State Vector (Sprint 3 Jalon 3)
// ─────────────────────────────────────────────────────────────────────────

export type EnergyBudget = "high" | "normal" | "low";

export interface UserStateResponse {
  mood: string;
  current_focus: string;
  recent_topics: string[];
  open_loops: string[];
  energy_budget: EnergyBudget;
  updated_at: string | null;
  prompt_version: string | null;
  disabled: boolean;
}

// ─────────────────────────────────────────────────────────────────────────
// My learned skills (Sprint 4b Phase 5.b)
// ─────────────────────────────────────────────────────────────────────────

/** A single LearnedSkill row from the user-facing surface. Mirrors
 *  `MeSkillOut` in `backend/app/routers/me_learning_skills.py`. */
export interface MeLearnedSkill {
  id: string;
  name: string;
  description: string;
  /** Full Markdown body, frontmatter stripped. Shown in the expand panel. */
  content: string;
  /** One of: `candidate`, `active`, `stale`, `archived`, `rejected`. */
  status: string;
  /** `auto_generated`, `user_added`, `imported_marketplace`. */
  source: string;
  iteration_count: number;
  last_eval_score: number | null;
  pinned: boolean;
  use_count: number;
  last_used_at: string | null;
  created_at: string | null;
  updated_at: string | null;
}
