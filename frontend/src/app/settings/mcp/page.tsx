"use client";
/**
 * @project    ELY — Exactly Like You
 * @file       frontend/src/app/settings/mcp/page.tsx
 * @brief      MCP servers — admin UI for registering external MCP tool servers
 *
 * @author     Franck OLLIVIER <contact@agent-ely.fr>
 * @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
 * @license    Elastic License 2.0
 *            https://www.elastic.co/licensing/elastic-license
 *
 * Sprint 4a J2 (2026-05-27) — admin UI for the MCP client.
 *
 * Each MCPServer DB row maps to one Skill in the registry (`mcp_<slug>`),
 * which exposes N LangChain tools. The agent auto-binds those tools via
 * the wire-up in resolve_profile_tools (J1.5a).
 */
import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import {
  Plug, Plus, RefreshCw, Trash2, Pencil, Save, X, ArrowLeft,
  CheckCircle2, AlertCircle, Loader2, Terminal, Wifi,
} from "lucide-react";
import { AdminGuard } from "@/components/layout/AuthGuard";
import { Sidebar } from "@/components/layout/Sidebar";
import { Header } from "@/components/layout/Header";
import { api, type MCPServerOut, type MCPServerCreateBody } from "@/lib/api";

type FormState = MCPServerCreateBody & { id?: string };

const EMPTY_FORM: FormState = {
  name: "",
  slug: "",
  transport: "stdio",
  command: "",
  url: "",
  env_json: "",
  description: "",
  enabled: true,
};

function toCreateBody(form: FormState): MCPServerCreateBody {
  // Send only the relevant transport field; leave the other null so the
  // backend doesn't store a stale command on an SSE server (and vice versa).
  const body: MCPServerCreateBody = {
    name: form.name.trim(),
    slug: form.slug.trim(),
    transport: form.transport,
    description: (form.description || "").trim() || null,
    env_json: (form.env_json || "").trim() || null,
    enabled: form.enabled ?? true,
    command: form.transport === "stdio" ? (form.command || "").trim() || null : null,
    url: form.transport === "sse" ? (form.url || "").trim() || null : null,
  };
  return body;
}

function validate(form: FormState): string | null {
  if (!form.name.trim()) return "Le nom est requis.";
  if (!form.slug.trim()) return "Le slug est requis.";
  if (!/^[a-z0-9][a-z0-9_-]{1,63}$/.test(form.slug.trim())) {
    return "Slug invalide — minuscules, chiffres, tirets/underscores, 2-64 caractères.";
  }
  if (form.transport === "stdio" && !(form.command || "").trim()) {
    return "La commande est requise pour le transport stdio (ex. « uv tool run mcp-server-time »).";
  }
  if (form.transport === "sse" && !(form.url || "").trim()) {
    return "L'URL est requise pour le transport SSE.";
  }
  if ((form.env_json || "").trim()) {
    try {
      const parsed = JSON.parse(form.env_json!);
      if (typeof parsed !== "object" || Array.isArray(parsed) || parsed === null) {
        return "env_json doit être un objet JSON (ex. {\"GITHUB_TOKEN\":\"ghp_…\"}).";
      }
    } catch {
      return "env_json n'est pas du JSON valide.";
    }
  }
  return null;
}

export default function MCPSettingsPage() {
  const [servers, setServers] = useState<MCPServerOut[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string>("");
  const [toast, setToast] = useState<{ kind: "ok" | "err"; msg: string } | null>(null);

  const [form, setForm] = useState<FormState>(EMPTY_FORM);
  const [showForm, setShowForm] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  const [reloadingId, setReloadingId] = useState<string | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      setError("");
      const data = await api.mcpServersList();
      setServers(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const showToast = useCallback((kind: "ok" | "err", msg: string) => {
    setToast({ kind, msg });
    setTimeout(() => setToast(null), 3500);
  }, []);

  const startEdit = useCallback((srv: MCPServerOut) => {
    setForm({
      id: srv.id,
      name: srv.name,
      slug: srv.slug,
      transport: srv.transport,
      command: srv.command ?? "",
      url: srv.url ?? "",
      env_json: srv.env_json ?? "",
      description: srv.description ?? "",
      enabled: srv.enabled,
    });
    setShowForm(true);
  }, []);

  const cancelForm = useCallback(() => {
    setForm(EMPTY_FORM);
    setShowForm(false);
  }, []);

  const handleSubmit = useCallback(async () => {
    const err = validate(form);
    if (err) {
      showToast("err", err);
      return;
    }
    setSubmitting(true);
    try {
      const body = toCreateBody(form);
      if (form.id) {
        await api.mcpServerUpdate(form.id, body);
        showToast("ok", `Serveur « ${body.name} » mis à jour.`);
      } else {
        await api.mcpServerCreate(body);
        showToast("ok", `Serveur « ${body.name} » créé.`);
      }
      await refresh();
      cancelForm();
    } catch (e) {
      showToast("err", e instanceof Error ? e.message : String(e));
    } finally {
      setSubmitting(false);
    }
  }, [form, refresh, cancelForm, showToast]);

  const handleReload = useCallback(
    async (srv: MCPServerOut) => {
      setReloadingId(srv.id);
      try {
        const res = await api.mcpServerReload(srv.id);
        showToast(
          "ok",
          `« ${srv.name} » rechargé — ${res.tools.length} tool(s) : ${res.tools.join(", ") || "(aucun)"}.`,
        );
        await refresh();
      } catch (e) {
        showToast("err", e instanceof Error ? e.message : String(e));
      } finally {
        setReloadingId(null);
      }
    },
    [refresh, showToast],
  );

  const handleDelete = useCallback(
    async (srv: MCPServerOut) => {
      if (!confirm(`Supprimer le serveur MCP « ${srv.name} » ? Les outils seront retirés du registry.`)) return;
      setDeletingId(srv.id);
      try {
        await api.mcpServerDelete(srv.id);
        showToast("ok", `Serveur « ${srv.name} » supprimé.`);
        await refresh();
      } catch (e) {
        showToast("err", e instanceof Error ? e.message : String(e));
      } finally {
        setDeletingId(null);
      }
    },
    [refresh, showToast],
  );

  return (
    <AdminGuard>
      <div className="flex h-screen bg-bg-primary text-text-primary">
        <Sidebar />
        <div className="flex-1 flex flex-col overflow-hidden">
          <Header />
          <main className="flex-1 overflow-y-auto px-4 sm:px-6 py-6 max-w-6xl w-full mx-auto space-y-6">
            {/* Breadcrumb */}
            <div className="flex items-center gap-2 text-xs text-text-muted">
              <Link href="/admin" className="flex items-center gap-1 hover:text-text-secondary">
                <ArrowLeft className="w-3 h-3" />
                Admin
              </Link>
              <span>›</span>
              <span className="text-text-primary">MCP servers</span>
            </div>

            {/* Header card */}
            <div className="bg-bg-secondary border border-border-dim rounded-lg p-5 space-y-2">
              <div className="flex items-center gap-2">
                <Plug className="w-5 h-5 text-cyber-cyan" />
                <h1 className="text-base font-semibold">Serveurs MCP</h1>
              </div>
              <p className="text-xs text-text-muted leading-relaxed">
                Chaque serveur MCP est lancé en sous-processus par le backend et expose ses outils à ELY
                via le registry. Les outils MCP passent automatiquement le filtre du profil <code>default</code>
                (wire-up Sprint 4a J1.5a). <strong>Admin uniquement</strong>.
              </p>
              <p className="text-[11px] text-text-muted">
                Exemples : <code>uv tool run mcp-server-time</code>,{" "}
                <code>uv tool run mcp-server-fetch</code>, <code>npx -y @modelcontextprotocol/server-filesystem /tmp</code>.
              </p>
            </div>

            {/* Toast */}
            {toast && (
              <div
                className={`rounded-md border px-3 py-2 text-xs flex items-center gap-2 ${
                  toast.kind === "ok"
                    ? "border-cyber-green/30 text-cyber-green bg-cyber-green/5"
                    : "border-cyber-red/30 text-cyber-red bg-cyber-red/5"
                }`}
              >
                {toast.kind === "ok" ? <CheckCircle2 className="w-3.5 h-3.5" /> : <AlertCircle className="w-3.5 h-3.5" />}
                <span>{toast.msg}</span>
              </div>
            )}

            {/* Actions */}
            <div className="flex items-center justify-between">
              <div className="text-xs text-text-muted">
                {loading
                  ? "Chargement…"
                  : `${servers.length} serveur${servers.length > 1 ? "s" : ""} configuré${servers.length > 1 ? "s" : ""}.`}
              </div>
              {!showForm && (
                <button
                  onClick={() => {
                    setForm(EMPTY_FORM);
                    setShowForm(true);
                  }}
                  className="px-3 py-1.5 rounded border border-cyber-cyan/30 text-cyber-cyan hover:bg-cyber-cyan/5 transition-all flex items-center gap-1.5 text-xs"
                >
                  <Plus className="w-3.5 h-3.5" />
                  Ajouter un serveur
                </button>
              )}
            </div>

            {error && (
              <div className="rounded-md border border-cyber-red/30 bg-cyber-red/5 px-3 py-2 text-xs text-cyber-red flex items-center gap-2">
                <AlertCircle className="w-3.5 h-3.5" />
                {error}
              </div>
            )}

            {/* Add/Edit form */}
            {showForm && (
              <div className="bg-bg-secondary border border-cyber-cyan/30 rounded-lg p-4 space-y-3">
                <div className="flex items-center justify-between">
                  <h2 className="text-sm font-semibold">
                    {form.id ? "Modifier le serveur" : "Nouveau serveur MCP"}
                  </h2>
                  <button
                    onClick={cancelForm}
                    className="text-text-muted hover:text-text-secondary"
                    aria-label="Fermer"
                  >
                    <X className="w-4 h-4" />
                  </button>
                </div>

                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                  <Field label="Nom" hint="Affiché dans le panneau & les logs.">
                    <input
                      type="text"
                      value={form.name}
                      onChange={(e) => setForm({ ...form, name: e.target.value })}
                      placeholder="Time (USA + EU)"
                      className="ely-input"
                    />
                  </Field>

                  <Field label="Slug" hint="Identifiant unique, kebab-case (a-z, 0-9, -, _).">
                    <input
                      type="text"
                      value={form.slug}
                      onChange={(e) => setForm({ ...form, slug: e.target.value.toLowerCase() })}
                      placeholder="time"
                      disabled={!!form.id}
                      className="ely-input disabled:opacity-50"
                    />
                  </Field>

                  <Field label="Transport" hint="stdio = sous-processus local. sse = HTTP distant.">
                    <select
                      value={form.transport}
                      onChange={(e) => setForm({ ...form, transport: e.target.value as "stdio" | "sse" })}
                      className="ely-input"
                    >
                      <option value="stdio">stdio (sous-processus)</option>
                      <option value="sse">sse (HTTP)</option>
                    </select>
                  </Field>

                  <Field
                    label={form.transport === "stdio" ? "Commande" : "URL"}
                    hint={
                      form.transport === "stdio"
                        ? "Ligne de commande complète, comme dans un terminal."
                        : "Base URL du serveur SSE (incluant /sse)."
                    }
                  >
                    {form.transport === "stdio" ? (
                      <input
                        type="text"
                        value={form.command ?? ""}
                        onChange={(e) => setForm({ ...form, command: e.target.value })}
                        placeholder="uv tool run mcp-server-time"
                        className="ely-input"
                      />
                    ) : (
                      <input
                        type="text"
                        value={form.url ?? ""}
                        onChange={(e) => setForm({ ...form, url: e.target.value })}
                        placeholder="http://localhost:3000/sse"
                        className="ely-input"
                      />
                    )}
                  </Field>

                  <div className="sm:col-span-2">
                    <Field
                      label="env_json (optionnel)"
                      hint="Objet JSON ajouté à l'env du sous-processus. Les clés ELY (ANTHROPIC_API_KEY, etc.) sont filtrées avant. L'admin peut ré-injecter une clé explicite ici."
                    >
                      <textarea
                        value={form.env_json ?? ""}
                        onChange={(e) => setForm({ ...form, env_json: e.target.value })}
                        placeholder='{"GITHUB_PERSONAL_ACCESS_TOKEN":"ghp_..."}'
                        rows={2}
                        className="ely-input font-mono text-[11px]"
                      />
                    </Field>
                  </div>

                  <div className="sm:col-span-2">
                    <Field label="Description (optionnel)" hint="Visible dans le panneau, non envoyée au LLM.">
                      <input
                        type="text"
                        value={form.description ?? ""}
                        onChange={(e) => setForm({ ...form, description: e.target.value })}
                        placeholder="Time MCP server — Europe/Paris + conversions."
                        className="ely-input"
                      />
                    </Field>
                  </div>

                  <div className="sm:col-span-2 flex items-center gap-2 text-xs">
                    <input
                      type="checkbox"
                      id="enabled"
                      checked={form.enabled ?? true}
                      onChange={(e) => setForm({ ...form, enabled: e.target.checked })}
                      className="accent-cyber-cyan"
                    />
                    <label htmlFor="enabled" className="cursor-pointer">
                      Activé — l'outil sera chargé au démarrage et bindé au LLM.
                    </label>
                  </div>
                </div>

                <div className="flex items-center gap-2 pt-2">
                  <button
                    onClick={handleSubmit}
                    disabled={submitting}
                    className="px-3 py-1.5 rounded border border-cyber-cyan/30 text-cyber-cyan hover:bg-cyber-cyan/5 transition-all flex items-center gap-1.5 text-xs disabled:opacity-40"
                  >
                    {submitting ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Save className="w-3.5 h-3.5" />}
                    {form.id ? "Enregistrer" : "Créer"}
                  </button>
                  <button
                    onClick={cancelForm}
                    disabled={submitting}
                    className="px-3 py-1.5 rounded border border-border-dim text-text-muted hover:text-text-secondary transition-all text-xs"
                  >
                    Annuler
                  </button>
                </div>
              </div>
            )}

            {/* Server list */}
            {!loading && servers.length === 0 && !showForm && (
              <div className="bg-bg-secondary border border-border-dim rounded-lg p-6 text-center space-y-2">
                <Plug className="w-8 h-8 text-text-muted mx-auto" />
                <p className="text-sm text-text-secondary">Aucun serveur MCP configuré.</p>
                <p className="text-xs text-text-muted">
                  Clique « Ajouter un serveur » pour exposer un MCP externe à ELY.
                </p>
              </div>
            )}

            {servers.length > 0 && (
              <div className="bg-bg-secondary border border-border-dim rounded-lg overflow-hidden">
                <table className="w-full text-xs">
                  <thead className="bg-bg-primary/50 border-b border-border-dim text-text-muted uppercase tracking-wider text-[10px]">
                    <tr>
                      <th className="text-left px-3 py-2">Nom / Slug</th>
                      <th className="text-left px-3 py-2">Transport</th>
                      <th className="text-left px-3 py-2">Cible</th>
                      <th className="text-left px-3 py-2">Outils</th>
                      <th className="text-right px-3 py-2">Actions</th>
                    </tr>
                  </thead>
                  <tbody>
                    {servers.map((srv) => (
                      <tr key={srv.id} className="border-b border-border-dim last:border-0 hover:bg-bg-primary/30">
                        <td className="px-3 py-2 align-top">
                          <div className="font-medium text-text-primary">{srv.name}</div>
                          <div className="text-text-muted font-mono text-[10px]">{srv.slug}</div>
                          {srv.description && (
                            <div className="text-text-muted text-[11px] mt-1 max-w-xs">{srv.description}</div>
                          )}
                        </td>
                        <td className="px-3 py-2 align-top">
                          <span className="inline-flex items-center gap-1 text-text-secondary">
                            {srv.transport === "stdio" ? (
                              <Terminal className="w-3 h-3" />
                            ) : (
                              <Wifi className="w-3 h-3" />
                            )}
                            {srv.transport}
                          </span>
                        </td>
                        <td className="px-3 py-2 align-top font-mono text-[10px] text-text-muted break-all max-w-xs">
                          {srv.transport === "stdio" ? srv.command : srv.url}
                        </td>
                        <td className="px-3 py-2 align-top">
                          {srv.tool_count === null ? (
                            <span className="text-text-muted">
                              {srv.enabled ? "—" : "désactivé"}
                            </span>
                          ) : (
                            <div>
                              <div className="text-cyber-green font-medium">{srv.tool_count}</div>
                              {srv.tool_names && srv.tool_names.length > 0 && (
                                <div className="text-text-muted text-[10px] max-w-xs font-mono">
                                  {srv.tool_names.join(", ")}
                                </div>
                              )}
                            </div>
                          )}
                        </td>
                        <td className="px-3 py-2 align-top">
                          <div className="flex items-center justify-end gap-1">
                            <button
                              onClick={() => handleReload(srv)}
                              disabled={reloadingId === srv.id || !srv.enabled}
                              title={srv.enabled ? "Recharger les outils" : "Activer le serveur pour pouvoir le recharger"}
                              className="p-1.5 rounded border border-border-dim text-text-muted hover:text-cyber-cyan hover:border-cyber-cyan/30 transition-all disabled:opacity-30 disabled:cursor-not-allowed"
                            >
                              {reloadingId === srv.id ? (
                                <Loader2 className="w-3.5 h-3.5 animate-spin" />
                              ) : (
                                <RefreshCw className="w-3.5 h-3.5" />
                              )}
                            </button>
                            <button
                              onClick={() => startEdit(srv)}
                              title="Modifier"
                              className="p-1.5 rounded border border-border-dim text-text-muted hover:text-text-primary hover:border-text-secondary/30 transition-all"
                            >
                              <Pencil className="w-3.5 h-3.5" />
                            </button>
                            <button
                              onClick={() => handleDelete(srv)}
                              disabled={deletingId === srv.id}
                              title="Supprimer"
                              className="p-1.5 rounded border border-border-dim text-text-muted hover:text-cyber-red hover:border-cyber-red/30 transition-all disabled:opacity-30"
                            >
                              {deletingId === srv.id ? (
                                <Loader2 className="w-3.5 h-3.5 animate-spin" />
                              ) : (
                                <Trash2 className="w-3.5 h-3.5" />
                              )}
                            </button>
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </main>
        </div>
      </div>

      <style jsx global>{`
        .ely-input {
          width: 100%;
          background: var(--bg-primary, #0a0a0c);
          border: 1px solid var(--border-dim, rgba(255, 255, 255, 0.08));
          border-radius: 0.375rem;
          padding: 0.5rem 0.625rem;
          font-size: 0.75rem;
          color: var(--text-primary, #e5e7eb);
          outline: none;
          transition: border-color 120ms ease;
        }
        .ely-input:focus {
          border-color: rgba(34, 211, 238, 0.4);
        }
      `}</style>
    </AdminGuard>
  );
}

function Field({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: string;
  children: React.ReactNode;
}) {
  return (
    <div className="space-y-1">
      <label className="block text-[11px] text-text-muted uppercase tracking-wider">{label}</label>
      {children}
      {hint && <p className="text-[10px] text-text-muted">{hint}</p>}
    </div>
  );
}
