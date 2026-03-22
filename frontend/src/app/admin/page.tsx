"use client";

import { useEffect, useState } from "react";
import { AuthGuard } from "@/components/layout/AuthGuard";
import { Sidebar } from "@/components/layout/Sidebar";
import { Header } from "@/components/layout/Header";
import { api } from "@/lib/api";
import { authFetch } from "@/lib/auth";
import type { AuditLog } from "@/lib/types";
import { Shield, Users, Terminal, RefreshCw, Settings2, Eye, EyeOff, Save, Trash2, CheckCircle } from "lucide-react";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

interface AdminUser {
  id: string;
  username: string;
  email: string;
  role: string;
  is_active: boolean;
  created_at: string;
}

// ── Google OAuth config form ──────────────────────────────────────────────────

const GOOGLE_FIELDS = [
  { key: "google_client_id",     label: "Client ID",     is_secret: false, description: "Google OAuth2 Client ID" },
  { key: "google_client_secret", label: "Client Secret", is_secret: true,  description: "Google OAuth2 Client Secret" },
  { key: "google_redirect_uri",  label: "Redirect URI",  is_secret: false, description: "URI de redirection OAuth (doit correspondre à Google Cloud Console)" },
];

function OAuthConfigPanel() {
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
      alert(`Erreur lors de la sauvegarde de ${key}`);
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
        <p>Ces credentials sont <strong className="text-text-primary">partagés</strong> entre tous les utilisateurs de l'instance.</p>
        <p>Chaque utilisateur connecte son propre compte Google via Settings → Services Google.</p>
        <p className="text-[11px]">
          Créer sur&nbsp;
          <a href="https://console.cloud.google.com/" target="_blank" rel="noopener noreferrer" className="text-cyber-cyan hover:underline">
            console.cloud.google.com
          </a>
          &nbsp;→ API & Services → Identifiants → ID client OAuth 2.0 (Application Web)
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
                {saved[key] ? "OK" : "Sauver"}
              </button>
              <button
                onClick={() => handleDelete(key)}
                className="px-2 py-1.5 rounded border border-border-dim text-text-muted hover:text-cyber-red hover:border-cyber-red/30 transition-all"
                title="Supprimer"
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

export default function AdminPage() {
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [logs, setLogs] = useState<AuditLog[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [tab, setTab] = useState<"users" | "audit" | "oauth">("audit");

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
    <AuthGuard>
      <div className="flex h-screen overflow-hidden">
        <Sidebar />
        <div className="flex flex-col flex-1 overflow-hidden">
          <Header />
          <div className="flex-1 overflow-y-auto p-6 space-y-4">

            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <Shield className="w-4 h-4 text-cyber-cyan" />
                <h1 className="text-sm font-medium text-text-primary">Administration</h1>
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

            {/* Tabs */}
            <div className="flex rounded-lg bg-bg-primary border border-border-dim p-1 w-fit">
              {([
                { id: "audit", label: "Audit Logs",   icon: Terminal  },
                { id: "users", label: "Utilisateurs", icon: Users     },
                { id: "oauth", label: "OAuth Google", icon: Settings2 },
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
            {tab === "oauth" ? (
              <OAuthConfigPanel />
            ) : loading ? (
              <div className="text-sm text-text-muted py-8 text-center">Chargement...</div>
            ) : tab === "audit" ? (
              <div className="bg-bg-secondary border border-border-dim rounded-lg overflow-hidden">
                <div className="overflow-x-auto">
                  <table className="w-full text-xs">
                    <thead>
                      <tr className="border-b border-border-dim text-text-muted">
                        <th className="text-left px-4 py-3 font-medium">Heure</th>
                        <th className="text-left px-4 py-3 font-medium">Action</th>
                        <th className="text-left px-4 py-3 font-medium">Hôte</th>
                        <th className="text-left px-4 py-3 font-medium">Commande</th>
                        <th className="text-left px-4 py-3 font-medium">Résultat</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-border-dim">
                      {logs.length === 0 ? (
                        <tr><td colSpan={5} className="px-4 py-8 text-center text-text-muted">Aucun log.</td></tr>
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
              <div className="bg-bg-secondary border border-border-dim rounded-lg overflow-hidden">
                <table className="w-full text-xs">
                  <thead>
                    <tr className="border-b border-border-dim text-text-muted">
                      <th className="text-left px-4 py-3 font-medium">Utilisateur</th>
                      <th className="text-left px-4 py-3 font-medium">Email</th>
                      <th className="text-left px-4 py-3 font-medium">Rôle</th>
                      <th className="text-left px-4 py-3 font-medium">Statut</th>
                      <th className="text-left px-4 py-3 font-medium">Créé le</th>
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
                            u.is_active ? "text-cyber-cyan" : "text-cyber-red"
                          }`}>
                            {u.is_active ? "actif" : "désactivé"}
                          </span>
                        </td>
                        <td className="px-4 py-2.5 text-text-muted">
                          {new Date(u.created_at).toLocaleDateString()}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </div>
      </div>
    </AuthGuard>
  );
}
