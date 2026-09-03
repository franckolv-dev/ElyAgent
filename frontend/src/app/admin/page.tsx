"use client";
/**
 * @project    ELY — Exactly Like You
 * @file       frontend/src/app/admin/page.tsx
 * @brief      Admin dashboard page — system overview and management
 *
 * @author     Franck OLLIVIER <contact@agent-ely.fr>
 * @copyright  Copyright (c) 2025-2026 Franck OLLIVIER
 * @license    MIT
 *            https://opensource.org/licenses/MIT
 * @version    1.1.0
 * @link       https://github.com/franckolv-dev/PhysicalAgent
 *
 * RÉSUMÉ DES CONDITIONS :
 *   - AUTORISÉ : Usage personnel et professionnel interne (gratuit).
 *   - INTERDIT : Revente comme SaaS / service managé à des tiers.
 *   - INTERDIT : Suppression des notices de copyright ou de licence.
 */

import { useEffect, useState } from "react";
import { AdminGuard } from "@/components/layout/AuthGuard";
import { Sidebar } from "@/components/layout/Sidebar";
import { Header } from "@/components/layout/Header";
import { api } from "@/lib/api";
import { authFetch } from "@/lib/auth";
import type { AuditLog } from "@/lib/types";
import { Shield, Users, Terminal, RefreshCw, Settings2, Eye, EyeOff, Save, Trash2, CheckCircle, Send, UserPlus, KeyRound, Power, X, Plug } from "lucide-react";
import { useTranslations } from "next-intl";
import Link from "next/link";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

// ── HTTP error formatting (Pydantic 422 has detail as array, not string) ──
// FastAPI / Pydantic returns 422s with `{detail: [{loc, msg, type, ...}]}`.
// Passing that object straight into React rendering (or into a `text: string`
// state slot) crashes the page. This helper folds it back into a readable
// string. Falls back to `fallback` for shapes we don't recognise.
type ApiErrorShape = {
  detail?: string | Array<string | { msg?: unknown }> | unknown;
};
function formatApiError(err: unknown, fallback: string): string {
  if (!err || typeof err !== "object") return fallback;
  const detail = (err as ApiErrorShape).detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    const msgs = detail
      .map((d) => {
        if (typeof d === "string") return d;
        if (d && typeof d === "object" && "msg" in d) {
          const m = (d as { msg: unknown }).msg;
          return typeof m === "string" ? m : "";
        }
        return "";
      })
      .filter(Boolean);
    if (msgs.length) return msgs.join(" · ");
  }
  return fallback;
}

// ── Password strength rules (mirror backend/app/schemas/auth.py) ──────────
// Live-checked in the reset-password modal so the admin sees ahead of time
// what's missing. The backend still enforces them; this is pre-validation
// UX, not a security gate.
type PasswordRules = {
  length: boolean;
  upper: boolean;
  lower: boolean;
  digit: boolean;
  special: boolean;
  allOk: boolean;
};
function checkPasswordRules(pwd: string): PasswordRules {
  const length = pwd.length >= 12;
  const upper = /[A-Z]/.test(pwd);
  const lower = /[a-z]/.test(pwd);
  const digit = /\d/.test(pwd);
  const special = /[^a-zA-Z0-9]/.test(pwd);
  return {
    length, upper, lower, digit, special,
    allOk: length && upper && lower && digit && special,
  };
}

interface AdminUser {
  id: string;
  username: string;
  email: string;
  role: string;
  is_active: boolean;
  created_at: string;
}

// ── Google OAuth config form ──────────────────────────────────────────────────

function OAuthConfigPanel() {
  const t = useTranslations("admin");
  const GOOGLE_FIELDS = [
    { key: "google_client_id",     label: t("oauthClientIdLabel"),     is_secret: false, description: t("oauthClientIdDesc") },
    { key: "google_client_secret", label: t("oauthClientSecretLabel"), is_secret: true,  description: t("oauthClientSecretDesc") },
    { key: "google_redirect_uri",  label: t("oauthRedirectUriLabel"),  is_secret: false, description: t("oauthRedirectUriDesc") },
  ];
  const [values, setValues] = useState<Record<string, string>>({
    google_client_id: "",
    google_client_secret: "",
    google_redirect_uri: "http://localhost:8000/api/google/callback",
  });
  const [show, setShow] = useState<Record<string, boolean>>({});
  const [saving, setSaving] = useState<Record<string, boolean>>({});
  const [saved, setSaved] = useState<Record<string, boolean>>({});

  const handleSave = async (key: string, isSecret: boolean, description: string) => {
    if (!values[key]) return;
    setSaving((s) => ({ ...s, [key]: true }));
    try {
      await authFetch(`${API_URL}/admin/config`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ key, value: values[key], is_secret: isSecret, description }),
      });
      setSaved((s) => ({ ...s, [key]: true }));
      setTimeout(() => setSaved((s) => ({ ...s, [key]: false })), 2000);
    } catch {
      alert(t("saveError", { key }));
    } finally {
      setSaving((s) => ({ ...s, [key]: false }));
    }
  };

  const handleDelete = async (key: string) => {
    await authFetch(`${API_URL}/admin/config/${key}`, { method: "DELETE" });
    setValues((v) => ({ ...v, [key]: "" }));
  };

  return (
    <div className="bg-bg-secondary border border-border-dim rounded-lg p-4 space-y-4 max-w-xl">
      <div className="text-xs text-text-muted space-y-1">
        <p>{t.rich("oauthSharedNote", { strong: (chunks) => <strong className="text-text-primary">{chunks}</strong> })}</p>
        <p>{t("oauthUserNote")}</p>
        <p className="text-[11px]">
          {t("oauthCreateOn")}&nbsp;
          <a href="https://console.cloud.google.com/" target="_blank" rel="noopener noreferrer" className="text-cyber-cyan hover:underline">
            console.cloud.google.com
          </a>
          &nbsp;{t("oauthCreateOnSuffix")}
        </p>
      </div>

      <div className="space-y-3 pt-1">
        {GOOGLE_FIELDS.map(({ key, label, is_secret, description }) => (
          <div key={key} className="space-y-1">
            <label className="text-[11px] text-text-muted uppercase tracking-wider">{label}</label>
            <div className="flex gap-2">
              <div className="relative flex-1">
                <input
                  type={is_secret && !show[key] ? "password" : "text"}
                  value={values[key]}
                  onChange={(e) => setValues((v) => ({ ...v, [key]: e.target.value }))}
                  placeholder={is_secret ? "••••••••" : description}
                  className="w-full bg-bg-primary border border-border-dim rounded px-3 py-2 text-xs text-text-primary placeholder-text-muted focus:outline-none focus:border-cyber-cyan/40 pr-8"
                />
                {is_secret && (
                  <button
                    type="button"
                    onClick={() => setShow((s) => ({ ...s, [key]: !s[key] }))}
                    className="absolute right-2 top-1/2 -translate-y-1/2 text-text-muted hover:text-text-secondary"
                  >
                    {show[key] ? <EyeOff className="w-3.5 h-3.5" /> : <Eye className="w-3.5 h-3.5" />}
                  </button>
                )}
              </div>
              <button
                onClick={() => handleSave(key, is_secret, description)}
                disabled={saving[key] || !values[key]}
                className="px-2.5 py-1.5 rounded border border-cyber-cyan/30 text-cyber-cyan hover:bg-cyber-cyan/5 transition-all disabled:opacity-40 flex items-center gap-1 text-[11px]"
              >
                {saved[key] ? <CheckCircle className="w-3.5 h-3.5" /> : <Save className="w-3.5 h-3.5" />}
                {saved[key] ? t("savedBtn") : t("saveBtn")}
              </button>
              <button
                onClick={() => handleDelete(key)}
                className="px-2 py-1.5 rounded border border-border-dim text-text-muted hover:text-cyber-red hover:border-cyber-red/30 transition-all"
                title={t("deleteTooltip")}
              >
                <Trash2 className="w-3.5 h-3.5" />
              </button>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

// ── Telegram config ──────────────────────────────────────────────────────────

function TelegramConfigPanel() {
  const t = useTranslations("admin");
  const TELEGRAM_FIELDS = [
    { key: "telegram_bot_token", label: t("telegramBotTokenLabel"), is_secret: true, description: t("telegramBotTokenDesc") },
  ];
  const [values, setValues] = useState<Record<string, string>>({ telegram_bot_token: "" });
  const [show, setShow] = useState<Record<string, boolean>>({});
  const [saving, setSaving] = useState<Record<string, boolean>>({});
  const [saved, setSaved] = useState<Record<string, boolean>>({});

  const handleSave = async (key: string, isSecret: boolean, description: string) => {
    if (!values[key]) return;
    setSaving((s) => ({ ...s, [key]: true }));
    try {
      await authFetch(`${API_URL}/admin/config`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ key, value: values[key], is_secret: isSecret, description }),
      });
      setSaved((s) => ({ ...s, [key]: true }));
      setTimeout(() => setSaved((s) => ({ ...s, [key]: false })), 2000);
    } catch {
      alert(t("saveError", { key }));
    } finally {
      setSaving((s) => ({ ...s, [key]: false }));
    }
  };

  const handleDelete = async (key: string) => {
    await authFetch(`${API_URL}/admin/config/${key}`, { method: "DELETE" });
    setValues((v) => ({ ...v, [key]: "" }));
  };

  return (
    <div className="bg-bg-secondary border border-border-dim rounded-lg p-4 space-y-4 max-w-xl">
      <div className="text-xs text-text-muted space-y-1">
        <p>{t.rich("telegramIntro", { strong: (chunks) => <strong className="text-text-primary">{chunks}</strong> })}</p>
        <p className="text-[11px]">
          {t.rich("telegramStep1", {
            link: (chunks) => (
              <a href="https://t.me/BotFather" target="_blank" rel="noopener noreferrer" className="text-cyber-cyan hover:underline">{chunks}</a>
            ),
          })}
        </p>
        <p className="text-[11px]">
          {t("telegramStep2")}
        </p>
        <p className="text-[11px]">
          {t.rich("telegramStep3", { code: (chunks) => <code className="text-cyber-cyan">{chunks}</code> })}
        </p>
      </div>

      <div className="space-y-3 pt-1">
        {TELEGRAM_FIELDS.map(({ key, label, is_secret, description }) => (
          <div key={key} className="space-y-1">
            <label className="text-[11px] text-text-muted uppercase tracking-wider">{label}</label>
            <div className="flex gap-2">
              <div className="relative flex-1">
                <input
                  type={is_secret && !show[key] ? "password" : "text"}
                  value={values[key]}
                  onChange={(e) => setValues((v) => ({ ...v, [key]: e.target.value }))}
                  placeholder={is_secret ? "••••••••" : description}
                  className="w-full bg-bg-primary border border-border-dim rounded px-3 py-2 text-xs text-text-primary placeholder-text-muted focus:outline-none focus:border-cyber-cyan/40 pr-8"
                />
                {is_secret && (
                  <button
                    type="button"
                    onClick={() => setShow((s) => ({ ...s, [key]: !s[key] }))}
                    className="absolute right-2 top-1/2 -translate-y-1/2 text-text-muted hover:text-text-secondary"
                  >
                    {show[key] ? <EyeOff className="w-3.5 h-3.5" /> : <Eye className="w-3.5 h-3.5" />}
                  </button>
                )}
              </div>
              <button
                onClick={() => handleSave(key, is_secret, description)}
                disabled={saving[key] || !values[key]}
                className="px-2.5 py-1.5 rounded border border-cyber-cyan/30 text-cyber-cyan hover:bg-cyber-cyan/5 transition-all disabled:opacity-40 flex items-center gap-1 text-[11px]"
              >
                {saved[key] ? <CheckCircle className="w-3.5 h-3.5" /> : <Save className="w-3.5 h-3.5" />}
                {saved[key] ? t("savedBtn") : t("saveBtn")}
              </button>
              <button
                onClick={() => handleDelete(key)}
                className="px-2 py-1.5 rounded border border-border-dim text-text-muted hover:text-cyber-red hover:border-cyber-red/30 transition-all"
                title={t("deleteTooltip")}
              >
                <Trash2 className="w-3.5 h-3.5" />
              </button>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

// ── Main admin page ───────────────────────────────────────────────────────────

function CreateUserForm({ onCreated }: { onCreated: () => void }) {
  const t = useTranslations("admin");
  const [form, setForm]       = useState({ username: "", email: "", password: "", role: "user" });
  const [saving, setSaving]   = useState(false);
  const [success, setSuccess] = useState(false);
  const [err, setErr]         = useState("");

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSaving(true);
    setErr("");
    try {
      const res = await authFetch(`${API_URL}/auth/register`, {
        method:  "POST",
        headers: { "Content-Type": "application/json" },
        body:    JSON.stringify(form),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail ?? `Erreur ${res.status}`);
      setSuccess(true);
      setForm({ username: "", email: "", password: "", role: "user" });
      setTimeout(() => { setSuccess(false); onCreated(); }, 1500);
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : "Erreur lors de la création");
    } finally {
      setSaving(false);
    }
  };

  return (
    <form onSubmit={handleSubmit} className="bg-bg-secondary border border-border-dim rounded-lg p-4 space-y-3 max-w-sm">
      <div className="flex items-center gap-2 mb-1">
        <UserPlus className="w-3.5 h-3.5 text-cyber-cyan" />
        <span className="text-xs font-medium text-text-primary">{t("createAccount")}</span>
      </div>

      {[
        { key: "username", label: t("username"), type: "text",     placeholder: "alice" },
        { key: "email",    label: "Email",       type: "email",    placeholder: "alice@example.com" },
        { key: "password", label: t("password"), type: "password", placeholder: "••••••••" },
      ].map(({ key, label, type, placeholder }) => (
        <div key={key} className="space-y-1">
          <label className="text-[11px] text-text-muted uppercase tracking-wider">{label}</label>
          <input
            type={type}
            required
            value={form[key as keyof typeof form]}
            onChange={(e) => setForm((f) => ({ ...f, [key]: e.target.value }))}
            placeholder={placeholder}
            className="w-full bg-bg-primary border border-border-dim rounded px-3 py-2 text-xs text-text-primary placeholder-text-muted focus:outline-none focus:border-cyber-cyan/40"
          />
        </div>
      ))}

      <div className="space-y-1">
        <label className="text-[11px] text-text-muted uppercase tracking-wider">{t("role")}</label>
        <select
          value={form.role}
          onChange={(e) => setForm((f) => ({ ...f, role: e.target.value }))}
          className="w-full bg-bg-primary border border-border-dim rounded px-3 py-2 text-xs text-text-primary focus:outline-none focus:border-cyber-cyan/40"
        >
          <option value="user">{t("user")}</option>
          <option value="admin">{t("administrator")}</option>
        </select>
      </div>

      {err && <p className="text-[11px] text-cyber-red">{err}</p>}

      <button
        type="submit"
        disabled={saving}
        className="flex items-center gap-1.5 px-3 py-1.5 rounded border border-cyber-cyan/30 text-cyber-cyan hover:bg-cyber-cyan/5 text-xs transition-all disabled:opacity-50"
      >
        {success ? <CheckCircle className="w-3.5 h-3.5" /> : <UserPlus className="w-3.5 h-3.5" />}
        {success ? t("accountCreated") : saving ? t("creating") : t("createAccountBtn")}
      </button>
    </form>
  );
}

export default function AdminPage() {
  const t = useTranslations("admin");
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [logs, setLogs] = useState<AuditLog[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [tab, setTab] = useState<"users" | "audit" | "oauth" | "telegram">("audit");

  // Reset password modal
  const [resetTarget, setResetTarget] = useState<AdminUser | null>(null);
  const [resetPwd, setResetPwd]       = useState("");
  const [resetPwdShow, setResetPwdShow] = useState(false);
  const [resetSaving, setResetSaving]   = useState(false);
  const [actionMsg, setActionMsg]       = useState<{ kind: "ok" | "err"; text: string } | null>(null);

  const showMsg = (kind: "ok" | "err", text: string) => {
    setActionMsg({ kind, text });
    setTimeout(() => setActionMsg(null), 3000);
  };

  const handleResetPassword = async () => {
    if (!resetTarget || !resetPwd || resetSaving) return;
    setResetSaving(true);
    try {
      const res = await authFetch(`${API_URL}/admin/users/${resetTarget.id}/reset-password`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ new_password: resetPwd }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        // 422 here is, in practice, always the password-strength gate.
        // With the live indicator + disabled button this is unreachable
        // through the UI, but the server stays authoritative — when the
        // race does happen, we want a CONSIGNE message, not a crashy
        // technical dump of Pydantic violations.
        showMsg(
          "err",
          res.status === 422
            ? "Mot de passe non conforme : 12 caractères minimum, avec majuscule, minuscule, chiffre et caractère spécial."
            : formatApiError(err, `Erreur ${res.status}`),
        );
      } else {
        showMsg("ok", `Mot de passe de « ${resetTarget.username} » réinitialisé.`);
        setResetTarget(null);
        setResetPwd("");
      }
    } catch {
      showMsg("err", "Impossible de contacter le serveur.");
    } finally {
      setResetSaving(false);
    }
  };

  const handleToggleActive = async (user: AdminUser) => {
    try {
      const res = await authFetch(`${API_URL}/admin/users/${user.id}/toggle-active`, { method: "PATCH" });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        showMsg("err", formatApiError(err, `Erreur ${res.status}`));
      } else {
        const data = await res.json();
        showMsg("ok", data.message);
        setUsers((prev) => prev.map((u) => u.id === user.id ? { ...u, is_active: data.is_active } : u));
      }
    } catch {
      showMsg("err", "Impossible de contacter le serveur.");
    }
  };

  const load = async () => {
    setLoading(true);
    try {
      const [u, l] = await Promise.all([api.getUsers(), api.getAuditLogs(100)]);
      setUsers(u);
      setLogs(l);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Access denied — admin required");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, []);

  return (
    <AdminGuard>
      <div className="flex h-screen overflow-hidden">
        <Sidebar />
        <div className="flex flex-col flex-1 min-w-0 overflow-hidden">
        <Header />
        <div className="flex flex-1 overflow-hidden">
          <main className="flex-1 overflow-y-auto p-6 space-y-4" style={{ background: "var(--bg-app)" }}>

            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <Shield className="w-4 h-4 text-cyber-cyan" />
                <h1 className="text-sm font-medium text-text-primary">{t("title")}</h1>
              </div>
              <button
                onClick={load}
                className="flex items-center gap-1.5 text-xs text-text-muted hover:text-text-primary transition-colors"
              >
                <RefreshCw className="w-3.5 h-3.5" />
                Refresh
              </button>
            </div>

            {error && (
              <div className="bg-cyber-red/5 border border-cyber-red/20 rounded-lg px-4 py-3 text-sm text-cyber-red">
                {error}
              </div>
            )}

            {/* Quick links to dedicated admin pages */}
            <div className="flex flex-wrap items-center gap-2">
              <Link
                href="/settings/mcp"
                className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md border border-border-dim text-text-secondary hover:text-cyber-cyan hover:border-cyber-cyan/30 transition-all text-xs"
              >
                <Plug className="w-3.5 h-3.5" />
                MCP servers
              </Link>
            </div>

            {/* Tabs */}
            <div className="flex rounded-lg bg-bg-primary border border-border-dim p-1 w-fit">
              {([
                { id: "audit", label: t("logs"),        icon: Terminal  },
                { id: "users", label: t("users"),      icon: Users     },
                { id: "oauth", label: t("oauthGoogle"), icon: Settings2 },
                { id: "telegram", label: t("telegram"), icon: Send     },
              ] as const).map(({ id, label, icon: Icon }) => (
                <button
                  key={id}
                  onClick={() => setTab(id)}
                  className={`flex items-center gap-1.5 px-4 py-1.5 rounded-md text-xs transition-all ${
                    tab === id
                      ? "bg-cyber-cyan/10 text-cyber-cyan border border-cyber-cyan/20"
                      : "text-text-muted hover:text-text-secondary"
                  }`}
                >
                  <Icon className="w-3.5 h-3.5" />
                  {label}
                </button>
              ))}
            </div>

            {/* Content */}
            {tab === "telegram" ? (
              <TelegramConfigPanel />
            ) : tab === "oauth" ? (
              <OAuthConfigPanel />
            ) : loading ? (
              <div className="text-sm text-text-muted py-8 text-center">{t("loading")}</div>
            ) : tab === "audit" ? (
              <div className="bg-bg-secondary border border-border-dim rounded-lg overflow-hidden">
                <div className="overflow-x-auto">
                  <table className="w-full text-xs">
                    <thead>
                      <tr className="border-b border-border-dim text-text-muted">
                        <th className="text-left px-4 py-3 font-medium">{t("time")}</th>
                        <th className="text-left px-4 py-3 font-medium">{t("action")}</th>
                        <th className="text-left px-4 py-3 font-medium">{t("host")}</th>
                        <th className="text-left px-4 py-3 font-medium">{t("command")}</th>
                        <th className="text-left px-4 py-3 font-medium">{t("result")}</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-border-dim">
                      {logs.length === 0 ? (
                        <tr><td colSpan={5} className="px-4 py-8 text-center text-text-muted">{t("noLogs")}</td></tr>
                      ) : logs.map((log) => (
                        <tr key={log.id} className="hover:bg-bg-tertiary/50">
                          <td className="px-4 py-2.5 text-text-muted whitespace-nowrap">
                            {new Date(log.created_at).toLocaleString()}
                          </td>
                          <td className="px-4 py-2.5">
                            <span className="px-1.5 py-0.5 rounded text-[10px] uppercase bg-cyber-cyan/10 text-cyber-cyan">
                              {log.action}
                            </span>
                          </td>
                          <td className="px-4 py-2.5 text-text-secondary">{log.target_host ?? "—"}</td>
                          <td className="px-4 py-2.5 font-mono text-text-primary max-w-xs truncate">
                            {log.command ?? "—"}
                          </td>
                          <td className="px-4 py-2.5">
                            {log.result_code !== null ? (
                              <span className={log.result_code === 0 ? "text-cyber-cyan" : "text-cyber-red"}>
                                [{log.result_code}]
                              </span>
                            ) : "—"}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            ) : (
              <div className="space-y-4">
                <CreateUserForm onCreated={load} />

                {/* Toast feedback */}
                {actionMsg && (
                  <div className={`flex items-center gap-2 px-4 py-2 rounded-lg border text-xs ${
                    actionMsg.kind === "ok"
                      ? "bg-emerald-900/60 border-emerald-500/30 text-emerald-300"
                      : "bg-red-900/60 border-red-500/30 text-red-300"
                  }`}>
                    {actionMsg.kind === "ok" ? <CheckCircle className="w-3.5 h-3.5" /> : <X className="w-3.5 h-3.5" />}
                    {actionMsg.text}
                  </div>
                )}

                {/* Reset password modal */}
                {resetTarget && (() => {
                  const rules = checkPasswordRules(resetPwd);
                  const ruleRows: Array<[boolean, string]> = [
                    [rules.length,  "12 caractères minimum"],
                    [rules.upper,   "1 lettre majuscule"],
                    [rules.lower,   "1 lettre minuscule"],
                    [rules.digit,   "1 chiffre"],
                    [rules.special, "1 caractère spécial"],
                  ];
                  return (
                  <div className="bg-bg-secondary border border-cyber-cyan/20 rounded-lg p-4 space-y-3">
                    <div className="flex items-center justify-between">
                      <p className="text-xs font-medium text-text-primary">
                        Réinitialiser le mot de passe de <span className="text-cyber-cyan">{resetTarget.username}</span>
                      </p>
                      <button onClick={() => { setResetTarget(null); setResetPwd(""); }} className="text-text-muted hover:text-text-primary">
                        <X className="w-3.5 h-3.5" />
                      </button>
                    </div>
                    <div className="relative">
                      <input
                        type={resetPwdShow ? "text" : "password"}
                        value={resetPwd}
                        onChange={(e) => setResetPwd(e.target.value)}
                        placeholder="Nouveau mot de passe"
                        className="w-full bg-bg-primary border border-border-dim rounded-md px-3 py-2 text-xs text-text-primary placeholder-text-muted/40 focus:outline-none focus:border-cyber-cyan/50 pr-9"
                      />
                      <button
                        type="button"
                        onClick={() => setResetPwdShow((v) => !v)}
                        className="absolute right-2.5 top-1/2 -translate-y-1/2 text-text-muted hover:text-text-secondary"
                      >
                        {resetPwdShow ? <EyeOff className="w-3 h-3" /> : <Eye className="w-3 h-3" />}
                      </button>
                    </div>
                    {/* Live password rules — backend rejects with 422 if any is missing.
                        Showing them inline avoids the surprise round-trip. Framed
                        as a CONSIGNE rather than a validation report — the admin
                        reads "voici ce que doit contenir le mot de passe", not
                        "voici les erreurs que vous faites". */}
                    <div className="text-[10px] text-text-muted">
                      Le mot de passe doit contenir :
                    </div>
                    <ul className="grid grid-cols-2 gap-x-3 gap-y-0.5 text-[10px]">
                      {ruleRows.map(([ok, label]) => (
                        <li key={label} className={ok ? "text-cyber-cyan" : "text-text-muted"}>
                          {ok ? "✓" : "○"} {label}
                        </li>
                      ))}
                    </ul>
                    <button
                      onClick={handleResetPassword}
                      disabled={resetSaving || !rules.allOk}
                      className="px-4 py-1.5 rounded text-xs bg-cyber-cyan/10 border border-cyber-cyan/30 text-cyber-cyan hover:bg-cyber-cyan/20 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
                      title={rules.allOk ? "" : "Toutes les règles doivent être satisfaites"}
                    >
                      {resetSaving ? "En cours…" : "Confirmer la réinitialisation"}
                    </button>
                  </div>
                  );
                })()}

              <div className="bg-bg-secondary border border-border-dim rounded-lg overflow-hidden">
                <table className="w-full text-xs">
                  <thead>
                    <tr className="border-b border-border-dim text-text-muted">
                      <th className="text-left px-4 py-3 font-medium">{t("username")}</th>
                      <th className="text-left px-4 py-3 font-medium">Email</th>
                      <th className="text-left px-4 py-3 font-medium">{t("role")}</th>
                      <th className="text-left px-4 py-3 font-medium">Statut</th>
                      <th className="text-left px-4 py-3 font-medium">Créé le</th>
                      <th className="text-left px-4 py-3 font-medium">Actions</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-border-dim">
                    {users.map((u) => (
                      <tr key={u.id} className="hover:bg-bg-tertiary/50">
                        <td className="px-4 py-2.5 text-text-primary font-medium">{u.username}</td>
                        <td className="px-4 py-2.5 text-text-secondary">{u.email}</td>
                        <td className="px-4 py-2.5">
                          <span className={`px-1.5 py-0.5 rounded text-[10px] uppercase ${
                            u.role === "admin"
                              ? "bg-cyber-purple/10 text-cyber-purple"
                              : "bg-bg-tertiary text-text-muted"
                          }`}>
                            {u.role}
                          </span>
                        </td>
                        <td className="px-4 py-2.5">
                          <span className={`px-1.5 py-0.5 rounded text-[10px] ${
                            u.is_active ? "text-cyber-cyan" : "text-red-400"
                          }`}>
                            {u.is_active ? "actif" : "désactivé"}
                          </span>
                        </td>
                        <td className="px-4 py-2.5 text-text-muted">
                          {new Date(u.created_at).toLocaleDateString()}
                        </td>
                        <td className="px-4 py-2.5">
                          <div className="flex items-center gap-2">
                            <button
                              onClick={() => { setResetTarget(u); setResetPwd(""); }}
                              title="Réinitialiser le mot de passe"
                              className="p-1 rounded text-text-muted hover:text-cyber-cyan hover:bg-cyber-cyan/10 transition-colors"
                            >
                              <KeyRound className="w-3.5 h-3.5" />
                            </button>
                            <button
                              onClick={() => handleToggleActive(u)}
                              title={u.is_active ? "Désactiver le compte" : "Activer le compte"}
                              className={`p-1 rounded transition-colors ${
                                u.is_active
                                  ? "text-text-muted hover:text-red-400 hover:bg-red-400/10"
                                  : "text-text-muted hover:text-emerald-400 hover:bg-emerald-400/10"
                              }`}
                            >
                              <Power className="w-3.5 h-3.5" />
                            </button>
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              </div>
            )}
          </main>
        </div>
        </div>
      </div>
    </AdminGuard>
  );
}
