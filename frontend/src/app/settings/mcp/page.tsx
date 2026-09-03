"use client";
/**
 * @project    ELY — Exactly Like You
 * @file       frontend/src/app/settings/mcp/page.tsx
 * @brief      MCP servers — admin UI for registering external MCP tool servers
 *
 * @author     Franck OLLIVIER <contact@agent-ely.fr>
 * @copyright  Copyright (c) 2025-2026 Franck OLLIVIER
 * @license    MIT
 *            https://opensource.org/licenses/MIT
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
  Upload, ShieldCheck, ShieldAlert, Lock, LogIn, LogOut, KeyRound,
  Users,
} from "lucide-react";

type OAuthStatus = { oauth: boolean; connected: boolean; locked?: boolean; scope?: string | null };
import { AdminGuard } from "@/components/layout/AuthGuard";
import { Sidebar } from "@/components/layout/Sidebar";
import { Header } from "@/components/layout/Header";
import {
  api,
  type MCPServerOut,
  type MCPServerCreateBody,
  type MCPPermissionOut,
  type MCPToolOut,
  type AdminUser,
} from "@/lib/api";

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
  auth_type: "none",
  oauth_client_id: "",
  oauth_scopes: "",
  allow_private_network: false,
};

function toCreateBody(form: FormState): MCPServerCreateBody {
  // Send only the relevant transport field; leave the other null so the
  // backend doesn't store a stale command on an HTTP server (and vice versa).
  const isStdio = form.transport === "stdio";
  const isOAuth = !isStdio && form.auth_type === "oauth2";
  const body: MCPServerCreateBody = {
    name: form.name.trim(),
    slug: form.slug.trim(),
    transport: form.transport,
    description: (form.description || "").trim() || null,
    env_json: (form.env_json || "").trim() || null,
    enabled: form.enabled ?? true,
    command: isStdio ? (form.command || "").trim() || null : null,
    url: !isStdio ? (form.url || "").trim() || null : null,
    // OAuth (J4) : config non secrète, seulement pour un serveur distant.
    auth_type: isStdio ? "none" : (form.auth_type || "none"),
    oauth_client_id: isOAuth ? (form.oauth_client_id || "").trim() || null : null,
    oauth_scopes: isOAuth ? (form.oauth_scopes || "").trim() || null : null,
    // Exception réseau privé/LAN : pertinente pour une cible distante uniquement.
    allow_private_network: isStdio ? false : !!form.allow_private_network,
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
  if (form.transport !== "stdio" && !(form.url || "").trim()) {
    return "L'URL est requise pour un transport distant (streamable_http / sse).";
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
  const [actioningId, setActioningId] = useState<string | null>(null);
  const [showImport, setShowImport] = useState(false);
  const [importText, setImportText] = useState("");
  const [importing, setImporting] = useState(false);

  // J4 — OAuth : statut de connexion per-user + spinners connect/disconnect.
  const [oauthStatus, setOauthStatus] = useState<Record<string, OAuthStatus>>({});
  const [connectingId, setConnectingId] = useState<string | null>(null);
  const [disconnectingId, setDisconnectingId] = useState<string | null>(null);

  // Accès utilisateurs — serveur dont le panneau de permissions est ouvert.
  const [permServer, setPermServer] = useState<MCPServerOut | null>(null);

  const refresh = useCallback(async () => {
    try {
      setError("");
      const data = await api.mcpServersList();
      setServers(data);
      // Statut OAuth per-user des serveurs oauth2 (fail-soft : un /status en
      // échec ne casse pas la page).
      const oauthSrvs = data.filter((s) => s.auth_type === "oauth2");
      if (oauthSrvs.length) {
        const entries = await Promise.all(
          oauthSrvs.map(async (s) => {
            try {
              return [s.id, await api.mcpOAuthStatus(s.id)] as const;
            } catch {
              return [s.id, null] as const;
            }
          }),
        );
        setOauthStatus(
          Object.fromEntries(entries.filter((e): e is readonly [string, OAuthStatus] => e[1] !== null)),
        );
      } else {
        setOauthStatus({});
      }
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

  // J4 — retour du callback OAuth : le backend redirige vers
  // /settings/mcp?mcp_oauth=connected|error|locked. On affiche un toast puis on
  // nettoie l'URL (pattern identique au flow Google).
  useEffect(() => {
    const r = new URLSearchParams(window.location.search).get("mcp_oauth");
    if (!r) return;
    if (r === "connected") {
      showToast("ok", "Serveur MCP connecté via OAuth.");
      // Recharge le statut pour que le badge passe « connecté » sans attendre
      // (symétrie avec handleOAuthDisconnect qui rafraîchit déjà).
      refresh();
    } else if (r === "locked")
      showToast("err", "Coffre-fort verrouillé — déverrouille-le puis réessaie « Se connecter ».");
    else showToast("err", "Connexion OAuth échouée.");
    window.history.replaceState({}, "", "/settings/mcp");
  }, [showToast, refresh]);

  const startEdit = useCallback((srv: MCPServerOut) => {
    setForm({
      id: srv.id,
      name: srv.name,
      slug: srv.slug,
      transport: srv.transport,
      command: srv.command ?? "",
      url: srv.url ?? "",
      // Secret-safe: env values are never returned by the API. Editing
      // leaves this blank — re-enter the secret if you need to change it.
      env_json: "",
      description: srv.description ?? "",
      enabled: srv.enabled,
      auth_type: srv.auth_type ?? "none",
      oauth_client_id: srv.oauth_client_id ?? "",
      oauth_scopes: srv.oauth_scopes ?? "",
      allow_private_network: srv.allow_private_network ?? false,
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

  const handleApprove = useCallback(
    async (srv: MCPServerOut) => {
      if (!confirm(
        `Approuver « ${srv.name} » ?\n\n` +
        (srv.transport === "stdio"
          ? "C'est un serveur LOCAL : l'approuver LANCE du code tiers sur la machine d'Ely."
          : "Le serveur sera activé et ses outils rendus disponibles."),
      )) return;
      setActioningId(srv.id);
      try {
        await api.mcpServerApprove(srv.id);
        showToast("ok", `« ${srv.name} » approuvé et activé.`);
        await refresh();
      } catch (e) {
        showToast("err", e instanceof Error ? e.message : String(e));
      } finally {
        setActioningId(null);
      }
    },
    [refresh, showToast],
  );

  const handleQuarantine = useCallback(
    async (srv: MCPServerOut) => {
      setActioningId(srv.id);
      try {
        await api.mcpServerQuarantine(srv.id);
        showToast("ok", `« ${srv.name} » remis en quarantaine.`);
        await refresh();
      } catch (e) {
        showToast("err", e instanceof Error ? e.message : String(e));
      } finally {
        setActioningId(null);
      }
    },
    [refresh, showToast],
  );

  const handleOAuthConnect = useCallback(
    async (srv: MCPServerOut) => {
      setConnectingId(srv.id);
      try {
        const { url } = await api.mcpOAuthStart(srv.id);
        // Redirection complète vers le serveur d'autorisation (comme Google).
        window.location.href = url;
      } catch (e) {
        showToast("err", e instanceof Error ? e.message : String(e));
        setConnectingId(null);
      }
    },
    [showToast],
  );

  const handleOAuthDisconnect = useCallback(
    async (srv: MCPServerOut) => {
      if (!confirm(
        `Te déconnecter de « ${srv.name} » ?\n\n` +
        "Tes tokens OAuth seront révoqués et purgés. Cela ne déconnecte que TOI " +
        "(les autres utilisateurs gardent leur connexion).",
      )) return;
      setDisconnectingId(srv.id);
      try {
        await api.mcpOAuthDisconnect(srv.id);
        showToast("ok", `Déconnecté de « ${srv.name} ».`);
        await refresh();
      } catch (e) {
        showToast("err", e instanceof Error ? e.message : String(e));
      } finally {
        setDisconnectingId(null);
      }
    },
    [refresh, showToast],
  );

  const handleImport = useCallback(async () => {
    let parsed: unknown;
    try {
      parsed = JSON.parse(importText);
    } catch {
      showToast("err", "JSON invalide.");
      return;
    }
    setImporting(true);
    try {
      const res = await api.mcpImport(parsed);
      showToast("ok", `${res.count} serveur(s) importé(s) en quarantaine — à approuver.`);
      setImportText("");
      setShowImport(false);
      await refresh();
    } catch (e) {
      showToast("err", e instanceof Error ? e.message : String(e));
    } finally {
      setImporting(false);
    }
  }, [importText, refresh, showToast]);

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
                <div className="flex items-center gap-2">
                  <button
                    onClick={() => setShowImport((v) => !v)}
                    className="px-3 py-1.5 rounded border border-border-dim text-text-muted hover:text-text-secondary transition-all flex items-center gap-1.5 text-xs"
                  >
                    <Upload className="w-3.5 h-3.5" />
                    Importer (mcpServers)
                  </button>
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
                </div>
              )}
            </div>

            {error && (
              <div className="rounded-md border border-cyber-red/30 bg-cyber-red/5 px-3 py-2 text-xs text-cyber-red flex items-center gap-2">
                <AlertCircle className="w-3.5 h-3.5" />
                {error}
              </div>
            )}

            {/* Import mcpServers JSON */}
            {showImport && (
              <div className="bg-bg-secondary border border-cyber-cyan/30 rounded-lg p-4 space-y-3">
                <div className="flex items-center justify-between">
                  <h2 className="text-sm font-semibold flex items-center gap-2">
                    <Upload className="w-4 h-4 text-cyber-cyan" />
                    Importer une configuration <code>mcpServers</code>
                  </h2>
                  <button onClick={() => setShowImport(false)} className="text-text-muted hover:text-text-secondary" aria-label="Fermer">
                    <X className="w-4 h-4" />
                  </button>
                </div>
                <p className="text-[11px] text-text-muted">
                  Chaque serveur est créé <strong>en quarantaine</strong> — jamais lancé ni activé
                  automatiquement. Tu l'approuves ensuite serveur par serveur.
                </p>
                <textarea
                  value={importText}
                  onChange={(e) => setImportText(e.target.value)}
                  placeholder={'{\n  "mcpServers": {\n    "filesystem": {\n      "command": "npx",\n      "args": ["-y", "@modelcontextprotocol/server-filesystem", "/data"]\n    }\n  }\n}'}
                  rows={8}
                  className="ely-input font-mono text-[11px]"
                />
                <div className="flex items-center gap-2">
                  <button
                    onClick={handleImport}
                    disabled={importing || !importText.trim()}
                    className="px-3 py-1.5 rounded border border-cyber-cyan/30 text-cyber-cyan hover:bg-cyber-cyan/5 transition-all flex items-center gap-1.5 text-xs disabled:opacity-40"
                  >
                    {importing ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Upload className="w-3.5 h-3.5" />}
                    Importer en quarantaine
                  </button>
                </div>
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

                  <Field label="Transport" hint="stdio = sous-processus local. streamable_http = HTTP distant (MCP moderne). sse = HTTP historique.">
                    <select
                      value={form.transport}
                      onChange={(e) => setForm({ ...form, transport: e.target.value as FormState["transport"] })}
                      className="ely-input"
                    >
                      <option value="stdio">stdio (sous-processus)</option>
                      <option value="streamable_http">streamable_http (HTTP)</option>
                      <option value="sse">sse (HTTP historique)</option>
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

                  {form.transport !== "stdio" && (
                    <>
                      <Field
                        label="Authentification"
                        hint="oauth2 = flow « Se connecter » (PKCE, tokens au Vault). Configurable depuis l'UI sans toucher la DB."
                      >
                        <select
                          value={form.auth_type ?? "none"}
                          onChange={(e) => setForm({ ...form, auth_type: e.target.value })}
                          className="ely-input"
                        >
                          <option value="none">none (public / sans auth)</option>
                          <option value="oauth2">oauth2 (Authorization Code + PKCE)</option>
                        </select>
                      </Field>
                      {form.auth_type === "oauth2" && (
                        <Field
                          label="client_id (optionnel)"
                          hint="Laisse vide pour l'enregistrement dynamique (DCR). Renseigne-le si le serveur ne supporte pas la DCR."
                        >
                          <input
                            type="text"
                            value={form.oauth_client_id ?? ""}
                            onChange={(e) => setForm({ ...form, oauth_client_id: e.target.value })}
                            placeholder="(DCR automatique si vide)"
                            className="ely-input"
                          />
                        </Field>
                      )}
                      {form.auth_type === "oauth2" && (
                        <div className="sm:col-span-2">
                          <Field
                            label="scopes (optionnel)"
                            hint="Scopes OAuth séparés par des espaces (ex. « repo read:user »). Vide = scopes annoncés par le serveur."
                          >
                            <input
                              type="text"
                              value={form.oauth_scopes ?? ""}
                              onChange={(e) => setForm({ ...form, oauth_scopes: e.target.value })}
                              placeholder="repo read:user"
                              className="ely-input"
                            />
                          </Field>
                        </div>
                      )}
                      <div className="sm:col-span-2 flex items-start gap-2 text-xs">
                        <input
                          type="checkbox"
                          id="allow_private_network"
                          checked={!!form.allow_private_network}
                          onChange={(e) => setForm({ ...form, allow_private_network: e.target.checked })}
                          className="mt-0.5 accent-amber-400"
                        />
                        <label htmlFor="allow_private_network" className="cursor-pointer text-text-muted">
                          <span className="text-amber-400">⚠️ Autoriser une cible réseau privée / LAN / localhost</span>
                          {" "}— désactive la garde SSRF pour CE serveur (à réserver à un serveur de
                          confiance sur ton réseau, ex. un serveur MCP de test local).
                        </label>
                      </div>
                    </>
                  )}

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
                      <th className="text-left px-3 py-2">État</th>
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
                        <td className="px-3 py-2 align-top">
                          <TrustBadge srv={srv} oauth={oauthStatus[srv.id]} />
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
                            {srv.trust_state === "quarantined" ? (
                              <button
                                onClick={() => handleApprove(srv)}
                                disabled={actioningId === srv.id}
                                title="Approuver et activer ce serveur"
                                className="p-1.5 rounded border border-cyber-green/30 text-cyber-green hover:bg-cyber-green/5 transition-all disabled:opacity-30"
                              >
                                {actioningId === srv.id ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <ShieldCheck className="w-3.5 h-3.5" />}
                              </button>
                            ) : srv.trust_state === "active" ? (
                              <button
                                onClick={() => handleQuarantine(srv)}
                                disabled={actioningId === srv.id}
                                title="Remettre en quarantaine (désactive le serveur)"
                                className="p-1.5 rounded border border-border-dim text-text-muted hover:text-amber-400 hover:border-amber-400/30 transition-all disabled:opacity-30"
                              >
                                {actioningId === srv.id ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <ShieldAlert className="w-3.5 h-3.5" />}
                              </button>
                            ) : null}
                            {srv.auth_type === "oauth2" && (
                              oauthStatus[srv.id]?.connected ? (
                                <button
                                  onClick={() => handleOAuthDisconnect(srv)}
                                  disabled={disconnectingId === srv.id}
                                  title="Te déconnecter (révoque tes tokens OAuth)"
                                  className="p-1.5 rounded border border-border-dim text-text-muted hover:text-amber-400 hover:border-amber-400/30 transition-all disabled:opacity-30"
                                >
                                  {disconnectingId === srv.id ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <LogOut className="w-3.5 h-3.5" />}
                                </button>
                              ) : (
                                <button
                                  onClick={() => handleOAuthConnect(srv)}
                                  disabled={connectingId === srv.id}
                                  title="Se connecter via OAuth"
                                  className="p-1.5 rounded border border-cyber-cyan/30 text-cyber-cyan hover:bg-cyber-cyan/5 transition-all disabled:opacity-30"
                                >
                                  {connectingId === srv.id ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <LogIn className="w-3.5 h-3.5" />}
                                </button>
                              )
                            )}
                            <button
                              onClick={() => setPermServer(srv)}
                              title="Gérer les accès utilisateurs (permissions MCP)"
                              className="p-1.5 rounded border border-border-dim text-text-muted hover:text-cyber-cyan hover:border-cyber-cyan/30 transition-all"
                            >
                              <Users className="w-3.5 h-3.5" />
                            </button>
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

            {/* Accès utilisateurs — permissions MCP par serveur */}
            {permServer && (
              <PermissionsPanel
                server={permServer}
                onClose={() => setPermServer(null)}
                showToast={showToast}
              />
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

/**
 * Panneau « Accès utilisateurs » d'un serveur MCP.
 *
 * Écrit dans mcp_tool_permissions : c'est le SEUL moyen pour l'admin d'ouvrir
 * un serveur d'instance à un autre utilisateur (le « Toujours autoriser » HITL
 * ne peut jamais écrire pour un non-admin refusé avant le HITL). Une règle
 * server-wide (tool = « tout le serveur ») suffit pour débloquer tous les
 * outils du serveur d'un coup. Aucun cache à invalider : l'ACL relit la DB.
 */
function PermissionsPanel({
  server,
  onClose,
  showToast,
}: {
  server: MCPServerOut;
  onClose: () => void;
  showToast: (kind: "ok" | "err", msg: string) => void;
}) {
  const [perms, setPerms] = useState<MCPPermissionOut[]>([]);
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [tools, setTools] = useState<MCPToolOut[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string>("");

  // Formulaire d'ajout.
  const [userId, setUserId] = useState<string>("");
  const [toolId, setToolId] = useState<string>("");   // "" ⇒ tout le serveur
  // Défaut « ask » : accès sans friction sur les outils anodins, confirmation
  // gardée sur les sensibles — plus sûr qu'« allow » par défaut.
  const [decision, setDecision] = useState<"allow" | "ask" | "deny">("ask");
  const [submitting, setSubmitting] = useState(false);
  const [deletingId, setDeletingId] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      setError("");
      const [p, u, t] = await Promise.all([
        api.mcpServerPermissions(server.id),
        api.getUsers(),
        api.mcpServerTools(server.id),
      ]);
      setPerms(p);
      setUsers(u);
      setTools(t);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, [server.id]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  // A11y : Échap ferme la modale (le clic sur le fond ferme déjà).
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const handleAdd = useCallback(async () => {
    if (!userId) {
      showToast("err", "Choisis un utilisateur.");
      return;
    }
    setSubmitting(true);
    try {
      await api.mcpServerPermissionCreate(server.id, {
        user_id: userId,
        tool_id: toolId || null,
        decision,
      });
      showToast("ok", "Règle d'accès enregistrée.");
      setUserId("");
      setToolId("");
      setDecision("ask");
      await refresh();
    } catch (e) {
      showToast("err", e instanceof Error ? e.message : String(e));
    } finally {
      setSubmitting(false);
    }
  }, [server.id, userId, toolId, decision, refresh, showToast]);

  const handleDelete = useCallback(
    async (perm: MCPPermissionOut) => {
      setDeletingId(perm.id);
      try {
        await api.mcpServerPermissionDelete(server.id, perm.id);
        showToast("ok", "Règle supprimée.");
        await refresh();
      } catch (e) {
        showToast("err", e instanceof Error ? e.message : String(e));
      } finally {
        setDeletingId(null);
      }
    },
    [server.id, refresh, showToast],
  );

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4"
      onClick={onClose}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="mcp-perms-title"
        className="bg-bg-secondary border border-cyber-cyan/30 rounded-lg w-full max-w-2xl max-h-[85vh] overflow-y-auto p-5 space-y-4"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between">
          <h2 id="mcp-perms-title" className="text-sm font-semibold flex items-center gap-2">
            <Users className="w-4 h-4 text-cyber-cyan" />
            Accès utilisateurs — <span className="font-mono text-cyber-cyan">{server.name}</span>
          </h2>
          <button onClick={onClose} className="text-text-muted hover:text-text-secondary" aria-label="Fermer">
            <X className="w-4 h-4" />
          </button>
        </div>

        <p className="text-[11px] text-text-muted leading-relaxed">
          {server.scope === "user" ? (
            <>
              Ce serveur est <strong>personnel</strong> : seul son propriétaire l'utilise. Les règles
              ci-dessous affinent le HITL, mais n'ouvrent l'accès à personne d'autre.
            </>
          ) : (
            <>
              Un serveur d'<strong>instance</strong> est réservé à l'admin. Ajoute une règle{" "}
              <span className="text-cyber-green">allow</span> pour ouvrir un outil (ou{" "}
              <strong>tout le serveur</strong>) à un autre utilisateur. Une règle{" "}
              <span className="text-cyber-red">deny</span> le bloque explicitement.
            </>
          )}
        </p>

        {error && (
          <div className="rounded-md border border-cyber-red/30 bg-cyber-red/5 px-3 py-2 text-xs text-cyber-red flex items-center gap-2">
            <AlertCircle className="w-3.5 h-3.5" />
            {error}
          </div>
        )}

        {/* Formulaire d'ajout */}
        <div className="grid grid-cols-1 sm:grid-cols-4 gap-2 items-end">
          <div className="sm:col-span-2 space-y-1">
            <label className="block text-[10px] text-text-muted uppercase tracking-wider">Utilisateur</label>
            <select
              value={userId}
              onChange={(e) => setUserId(e.target.value)}
              className="ely-input"
            >
              <option value="">— choisir —</option>
              {users.map((u) => (
                <option key={u.id} value={u.id}>
                  {u.username} ({u.email}){u.role === "admin" ? " · admin" : ""}
                </option>
              ))}
            </select>
          </div>
          <div className="space-y-1">
            <label className="block text-[10px] text-text-muted uppercase tracking-wider">Portée</label>
            <select
              value={toolId}
              onChange={(e) => setToolId(e.target.value)}
              className="ely-input"
            >
              <option value="">Tout le serveur</option>
              {tools.map((t) => (
                <option key={t.id} value={t.id}>
                  {t.remote_name}
                </option>
              ))}
            </select>
          </div>
          <div className="space-y-1">
            <label className="block text-[10px] text-text-muted uppercase tracking-wider">Décision</label>
            <select
              value={decision}
              onChange={(e) => setDecision(e.target.value as "allow" | "ask" | "deny")}
              className="ely-input"
            >
              <option value="allow">allow</option>
              <option value="ask">ask</option>
              <option value="deny">deny</option>
            </select>
          </div>
          <div className="sm:col-span-4 space-y-2">
            <p className="text-[10px] text-text-muted">
              <span className="text-cyber-green">allow</span> = accès sans confirmation ·{" "}
              <span className="text-amber-400">ask</span> = accès mais confirmation (HITL) gardée sur
              les outils sensibles ·{" "}
              <span className="text-cyber-red">deny</span> = bloqué. Pour ouvrir tout un serveur sans
              lever la confirmation de ses outils dangereux, préfère <strong>ask</strong>.
            </p>
            <button
              onClick={handleAdd}
              disabled={submitting || !userId}
              className="px-3 py-1.5 rounded border border-cyber-cyan/30 text-cyber-cyan hover:bg-cyber-cyan/5 transition-all flex items-center gap-1.5 text-xs disabled:opacity-40"
            >
              {submitting ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Plus className="w-3.5 h-3.5" />}
              Ajouter la règle
            </button>
          </div>
        </div>

        {/* Liste des règles */}
        {loading ? (
          <div className="text-xs text-text-muted flex items-center gap-2">
            <Loader2 className="w-3.5 h-3.5 animate-spin" /> Chargement…
          </div>
        ) : perms.length === 0 ? (
          <div className="text-xs text-text-muted text-center py-4">
            Aucune règle d'accès pour ce serveur.
          </div>
        ) : (
          <table className="w-full text-xs">
            <thead className="text-text-muted uppercase tracking-wider text-[10px] border-b border-border-dim">
              <tr>
                <th className="text-left px-2 py-1.5">Utilisateur</th>
                <th className="text-left px-2 py-1.5">Portée</th>
                <th className="text-left px-2 py-1.5">Décision</th>
                <th className="text-right px-2 py-1.5"></th>
              </tr>
            </thead>
            <tbody>
              {perms.map((p) => (
                <tr key={p.id} className="border-b border-border-dim last:border-0">
                  <td className="px-2 py-1.5">
                    <div className="text-text-primary">{p.username ?? p.user_id}</div>
                    {p.email && <div className="text-text-muted text-[10px]">{p.email}</div>}
                  </td>
                  <td className="px-2 py-1.5 font-mono text-[10px] text-text-muted">
                    {p.tool_name ?? "tout le serveur"}
                  </td>
                  <td className="px-2 py-1.5">
                    <span
                      className={`inline-flex items-center px-1.5 py-0.5 rounded border text-[10px] ${
                        p.decision === "allow"
                          ? "border-cyber-green/30 text-cyber-green bg-cyber-green/5"
                          : p.decision === "ask"
                          ? "border-amber-400/30 text-amber-400 bg-amber-400/5"
                          : "border-cyber-red/30 text-cyber-red bg-cyber-red/5"
                      }`}
                    >
                      {p.decision}
                    </span>
                  </td>
                  <td className="px-2 py-1.5 text-right">
                    <button
                      onClick={() => handleDelete(p)}
                      disabled={deletingId === p.id}
                      title="Supprimer la règle"
                      className="p-1 rounded border border-border-dim text-text-muted hover:text-cyber-red hover:border-cyber-red/30 transition-all disabled:opacity-30"
                    >
                      {deletingId === p.id ? (
                        <Loader2 className="w-3.5 h-3.5 animate-spin" />
                      ) : (
                        <Trash2 className="w-3.5 h-3.5" />
                      )}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}

function TrustBadge({ srv, oauth }: { srv: MCPServerOut; oauth?: OAuthStatus }) {
  const trust = srv.trust_state ?? "active";
  const health = srv.health_state ?? "unknown";
  const trustStyle =
    trust === "active"
      ? "border-cyber-green/30 text-cyber-green bg-cyber-green/5"
      : trust === "quarantined" || trust === "pending_approval"
      ? "border-amber-400/30 text-amber-400 bg-amber-400/5"
      : "border-cyber-red/30 text-cyber-red bg-cyber-red/5";
  const TrustIcon = trust === "active" ? ShieldCheck : ShieldAlert;
  return (
    <div className="space-y-1">
      <span className={`inline-flex items-center gap-1 px-1.5 py-0.5 rounded border text-[10px] ${trustStyle}`}>
        <TrustIcon className="w-3 h-3" />
        {trust}
      </span>
      <div className="flex items-center gap-1.5 text-[10px] text-text-muted">
        <span>{health}</span>
        {srv.scope === "user" && <span className="inline-flex items-center gap-0.5"><Lock className="w-2.5 h-2.5" />perso</span>}
        {srv.kill_switch && <span className="text-cyber-red">⛔ kill</span>}
      </div>
      {srv.auth_type === "oauth2" && (
        <div className="flex items-center gap-1 text-[10px]">
          <KeyRound className="w-2.5 h-2.5" />
          {oauth?.locked ? (
            <span className="text-amber-400">coffre verrouillé</span>
          ) : oauth?.connected ? (
            <span className="text-cyber-green">OAuth connecté</span>
          ) : (
            <span className="text-text-muted">OAuth non connecté</span>
          )}
        </div>
      )}
    </div>
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
