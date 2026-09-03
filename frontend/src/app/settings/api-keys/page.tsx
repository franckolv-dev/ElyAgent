"use client";
/**
 * @project    ELY — Exactly Like You
 * @file       frontend/src/app/settings/api-keys/page.tsx
 * @brief      Personal API key management UI (MCP server + API auth).
 *
 * @author     Franck OLLIVIER <contact@agent-ely.fr>
 * @copyright  Copyright (c) 2025-2026 Franck OLLIVIER
 * @license    MIT
 *            https://opensource.org/licenses/MIT
 *
 * Personal API keys authenticate non-browser clients — primarily ELY's own
 * MCP server (Claude Desktop & other MCP clients). Generated once, shown once,
 * hash-stored, revocable. Mirrors the extension-token UX.
 */
import { useCallback, useEffect, useState } from "react";
import {
  KeyRound, Plus, Trash2, Copy, AlertTriangle, CheckCircle2, Clock,
  ShieldOff, ArrowLeft, Loader2,
} from "lucide-react";
import Link from "next/link";
import { AuthGuard } from "@/components/layout/AuthGuard";
import { Sidebar } from "@/components/layout/Sidebar";
import { Header } from "@/components/layout/Header";
import { api } from "@/lib/api";

interface KeyListItem {
  id: string;
  name: string;
  last_4: string;
  created_at: string;
  last_used_at: string | null;
  revoked: boolean;
}

interface NewKey {
  id: string;
  name: string;
  key: string; // plaintext — visible until the user dismisses the box
  last_4: string;
  created_at: string;
}

function formatDate(iso: string | null): string {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString("fr-FR", {
      dateStyle: "short",
      timeStyle: "short",
    });
  } catch {
    return iso;
  }
}

export default function ApiKeysPage() {
  const [keys, setKeys] = useState<KeyListItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string>("");

  const [name, setName] = useState<string>("");
  const [creating, setCreating] = useState(false);
  const [newKey, setNewKey] = useState<NewKey | null>(null);
  const [copied, setCopied] = useState(false);

  const [revokingId, setRevokingId] = useState<string | null>(null);

  // MCP endpoint = this instance's origin + /api/mcp (computed client-side).
  const [mcpEndpoint, setMcpEndpoint] = useState("https://<votre-instance>/api/mcp");
  useEffect(() => {
    if (typeof window !== "undefined") {
      setMcpEndpoint(`${window.location.origin}/api/mcp`);
    }
  }, []);

  const refresh = useCallback(async () => {
    try {
      setError("");
      const data = await api.apiKeysList();
      setKeys(data as KeyListItem[]);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const handleCreate = useCallback(async () => {
    const trimmed = name.trim();
    if (!trimmed) {
      setError("Donnez un nom à cette clé (ex. « Claude Desktop »).");
      return;
    }
    setCreating(true);
    setError("");
    try {
      const data = (await api.apiKeyCreate(trimmed)) as NewKey;
      setNewKey(data);
      setName("");
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setCreating(false);
    }
  }, [name, refresh]);

  const handleCopy = useCallback(async () => {
    if (!newKey) return;
    try {
      await navigator.clipboard.writeText(newKey.key);
      setCopied(true);
      setTimeout(() => setCopied(false), 2500);
    } catch {
      const el = document.getElementById("new-key-input") as HTMLInputElement | null;
      if (el) {
        el.select();
        document.execCommand?.("copy");
        setCopied(true);
        setTimeout(() => setCopied(false), 2500);
      }
    }
  }, [newKey]);

  const handleRevoke = useCallback(
    async (id: string, label: string) => {
      const ok = window.confirm(
        `Révoquer la clé « ${label} » ?\n\n` +
          "Tout client (ex. Claude Desktop) qui l'utilise perdra immédiatement " +
          "l'accès et devra être reconfiguré avec une nouvelle clé.",
      );
      if (!ok) return;
      setRevokingId(id);
      try {
        await api.apiKeyRevoke(id);
        await refresh();
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
      } finally {
        setRevokingId(null);
      }
    },
    [refresh],
  );

  return (
    <AuthGuard>
      <style jsx>{`
        :global(.revoke-btn:hover:not(:disabled)) {
          background: rgba(239, 68, 68, 0.12) !important;
          border-color: rgba(239, 68, 68, 0.55) !important;
          color: rgb(248, 113, 113) !important;
        }
      `}</style>
      <div className="flex h-screen bg-[var(--bg)] text-[var(--text)]">
        <Sidebar />
        <div className="flex-1 flex flex-col overflow-hidden">
          <Header />
          <main className="flex-1 overflow-y-auto p-6 md:p-8">
            <div className="max-w-3xl mx-auto">
              <Link
                href="/settings"
                className="inline-flex items-center gap-2 text-sm text-[var(--text-2)] hover:text-[var(--text)] mb-6"
              >
                <ArrowLeft size={14} /> Réglages
              </Link>

              <header className="mb-6">
                <h1 className="text-2xl font-semibold flex items-center gap-2">
                  <KeyRound size={22} /> Clés API personnelles
                </h1>
                <p className="text-sm text-[var(--text-2)] mt-2 leading-relaxed">
                  Les clés API longue durée authentifient des clients
                  non-navigateur — en premier lieu le <strong>serveur MCP d’ELY</strong>
                  (Claude Desktop et autres clients MCP s’y connectent avec votre
                  clé). Chaque clé est affichée <strong>une seule fois</strong> à la
                  création — copiez-la immédiatement. Révocable à tout moment.
                </p>
              </header>

              {newKey && (
                <div
                  className="rounded-lg p-4 mb-6"
                  role="alert"
                  style={{
                    background: "rgba(245, 158, 11, 0.10)",
                    border: "1px solid rgba(245, 158, 11, 0.55)",
                    color: "var(--text)",
                  }}
                >
                  <div className="flex items-start gap-3">
                    <AlertTriangle
                      size={18}
                      className="flex-shrink-0 mt-0.5"
                      style={{ color: "rgb(245, 158, 11)" }}
                    />
                    <div className="flex-1 min-w-0">
                      <div className="font-semibold mb-1" style={{ color: "var(--text)" }}>
                        Clé créée : « {newKey.name} »
                      </div>
                      <p className="text-sm mb-3" style={{ color: "var(--text-2)" }}>
                        Copiez cette clé <strong style={{ color: "var(--text)" }}>maintenant</strong>.
                        Elle ne sera plus jamais affichée ; seuls les 4 derniers
                        caractères resteront visibles pour identification.
                      </p>
                      <div className="flex gap-2">
                        <input
                          id="new-key-input"
                          type="text"
                          readOnly
                          value={newKey.key}
                          onFocus={(e) => e.currentTarget.select()}
                          className="flex-1 font-mono text-sm px-3 py-2 rounded"
                          style={{
                            background: "var(--bg)",
                            border: "1px solid var(--border)",
                            color: "var(--text)",
                          }}
                        />
                        <button
                          type="button"
                          onClick={handleCopy}
                          className="px-3 py-2 rounded inline-flex items-center gap-2 text-sm"
                          style={{
                            background: "var(--bg-2)",
                            border: "1px solid var(--border)",
                            color: "var(--text)",
                          }}
                        >
                          {copied ? (
                            <>
                              <CheckCircle2 size={14} style={{ color: "rgb(34, 197, 94)" }} /> Copié
                            </>
                          ) : (
                            <>
                              <Copy size={14} /> Copier
                            </>
                          )}
                        </button>
                      </div>
                      <button
                        type="button"
                        onClick={() => setNewKey(null)}
                        className="mt-3 text-xs underline"
                        style={{ color: "var(--text-2)" }}
                      >
                        J’ai copié la clé, masquer
                      </button>
                    </div>
                  </div>
                </div>
              )}

              <section className="rounded-lg border border-[var(--border)] bg-[var(--bg-2)] p-4 mb-6">
                <h2 className="font-medium mb-3 flex items-center gap-2">
                  <Plus size={16} /> Générer une nouvelle clé
                </h2>
                <div className="flex flex-col sm:flex-row gap-2">
                  <input
                    type="text"
                    value={name}
                    placeholder="Ex : Claude Desktop, Laptop CLI…"
                    onChange={(e) => setName(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" && !creating) handleCreate();
                    }}
                    maxLength={100}
                    className="flex-1 px-3 py-2 rounded border border-[var(--border)] bg-[var(--bg)]"
                  />
                  <button
                    type="button"
                    onClick={handleCreate}
                    disabled={creating || !name.trim()}
                    className="px-4 py-2 rounded bg-[var(--accent)] text-white font-medium hover:opacity-90 disabled:opacity-50 disabled:cursor-not-allowed inline-flex items-center gap-2"
                  >
                    {creating ? (
                      <>
                        <Loader2 size={14} className="animate-spin" /> Génération…
                      </>
                    ) : (
                      <>
                        <Plus size={14} /> Générer
                      </>
                    )}
                  </button>
                </div>
                <p className="text-xs text-[var(--text-3)] mt-2">
                  Format : <code className="font-mono">ely_api_</code> + 64 caractères
                  hex (256 bits d’entropie). Pas de date d’expiration.
                </p>
              </section>

              {error && (
                <div
                  className="rounded-md text-sm px-3 py-2 mb-4"
                  style={{
                    background: "rgba(239, 68, 68, 0.12)",
                    border: "1px solid rgba(239, 68, 68, 0.55)",
                    color: "var(--text)",
                  }}
                >
                  {error}
                </div>
              )}

              <section>
                <h2 className="font-medium mb-3">Vos clés</h2>
                {loading ? (
                  <div className="text-sm text-[var(--text-2)] flex items-center gap-2">
                    <Loader2 size={14} className="animate-spin" /> Chargement…
                  </div>
                ) : keys.length === 0 ? (
                  <div className="rounded-lg border border-dashed border-[var(--border)] p-6 text-center text-sm text-[var(--text-2)]">
                    Aucune clé. Générez-en une ci-dessus pour connecter un client MCP.
                  </div>
                ) : (
                  <ul className="space-y-2">
                    {keys.map((k) => (
                      <li
                        key={k.id}
                        className="rounded-lg border border-[var(--border)] bg-[var(--bg-2)] p-3 flex items-center gap-3"
                        style={k.revoked ? { opacity: 0.6 } : undefined}
                      >
                        <div className="flex-1 min-w-0">
                          <div className="flex items-center gap-2 flex-wrap">
                            <span className="font-medium truncate">{k.name}</span>
                            <span className="font-mono text-xs text-[var(--text-3)]">
                              …{k.last_4}
                            </span>
                            {k.revoked && (
                              <span
                                className="inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded"
                                style={{
                                  background: "rgba(239, 68, 68, 0.15)",
                                  color: "rgb(248, 113, 113)",
                                  border: "1px solid rgba(239, 68, 68, 0.35)",
                                }}
                              >
                                <ShieldOff size={11} /> révoquée
                              </span>
                            )}
                          </div>
                          <div className="text-xs text-[var(--text-3)] mt-1 flex flex-wrap gap-x-4 gap-y-0.5">
                            <span className="inline-flex items-center gap-1">
                              <Clock size={11} /> Créée {formatDate(k.created_at)}
                            </span>
                            <span>Dernière utilisation : {formatDate(k.last_used_at)}</span>
                          </div>
                        </div>
                        {!k.revoked && (
                          <button
                            type="button"
                            onClick={() => handleRevoke(k.id, k.name)}
                            disabled={revokingId === k.id}
                            className="revoke-btn px-3 py-1.5 rounded inline-flex items-center gap-1.5 text-sm disabled:opacity-50"
                            style={{
                              background: "transparent",
                              border: "1px solid var(--border)",
                              color: "var(--text)",
                            }}
                            title="Révoquer cette clé"
                          >
                            {revokingId === k.id ? (
                              <Loader2 size={13} className="animate-spin" />
                            ) : (
                              <Trash2 size={13} />
                            )}
                            Révoquer
                          </button>
                        )}
                      </li>
                    ))}
                  </ul>
                )}
              </section>

              <section className="mt-8 text-xs text-[var(--text-3)] space-y-1">
                <p>
                  <strong>Comment l’utiliser :</strong> dans votre client MCP
                  (Claude Desktop…), ajoutez le serveur MCP d’ELY à l’adresse{" "}
                  <code className="font-mono">{mcpEndpoint}</code> et collez cette
                  clé comme jeton d’authentification (en-tête{" "}
                  <code className="font-mono">Authorization: Bearer ely_api_…</code>).
                  Outils exposés : <code className="font-mono">ely_chat</code>,{" "}
                  <code className="font-mono">ely_memory_search</code>,{" "}
                  <code className="font-mono">ely_list_scheduled_tasks</code>,{" "}
                  <code className="font-mono">ely_create_scheduled_task</code>.
                </p>
                <p>
                  <strong>Sécurité :</strong> seul le hash SHA-256 de la clé est
                  stocké côté serveur. Le plaintext ne quitte la base à aucun
                  moment — si vous le perdez, révoquez et régénérez.
                </p>
              </section>
            </div>
          </main>
        </div>
      </div>
    </AuthGuard>
  );
}
