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
};
