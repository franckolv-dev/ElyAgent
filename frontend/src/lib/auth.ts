/**
 * Auth helpers.
 *
 * Security model:
 *  - access_token  → in-memory (localStorage) — short lived (60 min)
 *  - refresh_token → HttpOnly cookie set by backend — never readable by JS
 *
 * The `refreshAccessToken()` call hits POST /api/auth/refresh; the browser
 * automatically sends the HttpOnly cookie. On success a new access_token is
 * stored and a rotated refresh cookie is set by the server.
 */

import type { TokenResponse, User } from "./types";

const TOKEN_KEY = "cyber_entity_token";
const API_BASE  = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

// ── Storage helpers ──────────────────────────────────────────────────────────

export function saveTokens(tokens: TokenResponse) {
  localStorage.setItem(TOKEN_KEY, tokens.access_token);
  // refresh_token is now an HttpOnly cookie — nothing to save here
}

export function getAccessToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem(TOKEN_KEY);
}

export function clearTokens() {
  localStorage.removeItem(TOKEN_KEY);
}

export function isAuthenticated(): boolean {
  return getAccessToken() !== null;
}

// ── Token refresh ────────────────────────────────────────────────────────────

let _refreshPromise: Promise<string | null> | null = null;

/**
 * Exchange the HttpOnly refresh cookie for a new access_token.
 * Concurrent callers share the same in-flight request.
 */
export async function refreshAccessToken(): Promise<string | null> {
  if (_refreshPromise) return _refreshPromise;

  _refreshPromise = (async () => {
    try {
      const res = await fetch(`${API_BASE}/auth/refresh`, {
        method: "POST",
        credentials: "include",   // sends the HttpOnly cookie
      });

      if (!res.ok) {
        clearTokens();
        return null;
      }

      const data = await res.json();
      localStorage.setItem(TOKEN_KEY, data.access_token);
      return data.access_token as string;
    } catch {
      clearTokens();
      return null;
    } finally {
      _refreshPromise = null;
    }
  })();

  return _refreshPromise;
}

// ── Authenticated fetch ──────────────────────────────────────────────────────

/**
 * Drop-in replacement for `fetch` that:
 *  1. Adds Authorization header automatically
 *  2. On 401 → tries one token refresh then retries
 *  3. On second 401 → clears session and throws
 */
export async function authFetch(
  input: RequestInfo,
  init: RequestInit = {},
): Promise<Response> {
  const token = getAccessToken();
  const headers = new Headers(init.headers ?? {});
  if (token) headers.set("Authorization", `Bearer ${token}`);

  const res = await fetch(input, { ...init, headers, credentials: "include" });

  if (res.status === 401) {
    const newToken = await refreshAccessToken();
    if (!newToken) throw new Error("Session expirée — veuillez vous reconnecter.");

    const retryHeaders = new Headers(init.headers ?? {});
    retryHeaders.set("Authorization", `Bearer ${newToken}`);
    return fetch(input, { ...init, headers: retryHeaders, credentials: "include" });
  }

  return res;
}

// ── Logout ───────────────────────────────────────────────────────────────────

export async function logout(): Promise<void> {
  try {
    await fetch(`${API_BASE}/auth/logout`, {
      method: "POST",
      credentials: "include",
    });
  } finally {
    clearTokens();
  }
}

// ── Re-exports expected by existing code ─────────────────────────────────────

/** @deprecated Use authFetch instead */
export async function fetchUser(): Promise<User | null> {
  try {
    const res = await authFetch(`${API_BASE}/auth/me`);
    if (!res.ok) return null;
    return res.json();
  } catch {
    return null;
  }
}
