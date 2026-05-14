"use client";
/**
 * @project    ELY — Exactly Like You
 * @file       frontend/src/app/settings/extension/page.tsx
 * @brief      Long-lived extension-token management UI (Sprint 0.5).
 *
 * @author     Franck OLLIVIER <contact@agent-ely.fr>
 * @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
 * @license    PolyForm Strict License 1.0.0
 *
 * Replaces the "open DevTools → copy localStorage.access_token" bidouille:
 *   1. User clicks "Generate".
 *   2. Server returns the plaintext token ONCE.
 *   3. UI shows it inside a copyable box with a clear warning: "you won't
 *      see this again, copy it now".
 *   4. The token can be pasted into the extension's Options page; the
 *      WebSocket then stays connected indefinitely (no 60-minute kick).
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

interface TokenListItem {
  id: string;
  name: string;
  last_4: string;
  created_at: string;
  last_used_at: string | null;
  revoked: boolean;
}

interface NewToken {
  id: string;
  name: string;
  token: string; // plaintext — visible until the user dismisses the box
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

export default function ExtensionTokensPage() {
  const [tokens, setTokens] = useState<TokenListItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string>("");

  const [name, setName] = useState<string>("");
  const [creating, setCreating] = useState(false);
  const [newToken, setNewToken] = useState<NewToken | null>(null);
  const [copied, setCopied] = useState(false);

  const [revokingId, setRevokingId] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      setError("");
      const data = await api.extensionTokensList();
      setTokens(data as TokenListItem[]);
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
      setError("Donnez un nom à ce token (ex. « Chrome Mac Studio »).");
      return;
    }
    setCreating(true);
    setError("");
    try {
      const data = (await api.extensionTokenCreate(trimmed)) as NewToken;
      setNewToken(data);
      setName("");
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setCreating(false);
    }
  }, [name, refresh]);

  const handleCopy = useCallback(async () => {
    if (!newToken) return;
    try {
      await navigator.clipboard.writeText(newToken.token);
      setCopied(true);
      setTimeout(() => setCopied(false), 2500);
    } catch {
      // Fallback: select text in the input.
      const el = document.getElementById("new-token-input") as HTMLInputElement | null;
      if (el) {
        el.select();
        document.execCommand?.("copy");
        setCopied(true);
        setTimeout(() => setCopied(false), 2500);
      }
    }
  }, [newToken]);

  const handleRevoke = useCallback(
    async (id: string, label: string) => {
      const ok = window.confirm(
        `Révoquer le token « ${label} » ?\n\n` +
          "L'extension Chrome qui l'utilise sera déconnectée immédiatement et " +
          "devra être reconfigurée avec un nouveau token.",
      );
      if (!ok) return;
      setRevokingId(id);
      try {
        await api.extensionTokenRevoke(id);
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
      {/* Inline styles for hover states that can't be expressed inline */}
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
                  <KeyRound size={22} /> Extension navigateur — tokens
                </h1>
                <p className="text-sm text-[var(--text-2)] mt-2 leading-relaxed">
                  Les tokens longue durée permettent à l’extension Chrome ELY
                  de rester connectée indéfiniment (au lieu de se déconnecter
                  toutes les 60 minutes avec le JWT classique). Chaque token est
                  affiché <strong>une seule fois</strong> à la création — copiez-le
                  immédiatement. Vous pouvez en révoquer un à tout moment.
                </p>
              </header>

              {/* New-token banner — only visible just after creation.
                  Theme-agnostic colors (semi-transparent amber overlay
                  + var(--text) for foreground) so the contrast holds
                  in both light and dark mode. */}
              {newToken && (
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
                      <div
                        className="font-semibold mb-1"
                        style={{ color: "var(--text)" }}
                      >
                        Token créé : « {newToken.name} »
                      </div>
                      <p
                        className="text-sm mb-3"
                        style={{ color: "var(--text-2)" }}
                      >
                        Copiez ce token <strong style={{ color: "var(--text)" }}>maintenant</strong>.
                        Il ne sera plus jamais affiché ; seuls les 4 derniers
                        caractères seront visibles pour identification.
                      </p>
                      <div className="flex gap-2">
                        <input
                          id="new-token-input"
                          type="text"
                          readOnly
                          value={newToken.token}
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
                        onClick={() => setNewToken(null)}
                        className="mt-3 text-xs underline"
                        style={{ color: "var(--text-2)" }}
                      >
                        J’ai copié le token, masquer
                      </button>
                    </div>
                  </div>
                </div>
              )}

              {/* Create form */}
              <section className="rounded-lg border border-[var(--border)] bg-[var(--bg-2)] p-4 mb-6">
                <h2 className="font-medium mb-3 flex items-center gap-2">
                  <Plus size={16} /> Générer un nouveau token
                </h2>
                <div className="flex flex-col sm:flex-row gap-2">
                  <input
                    type="text"
                    value={name}
                    placeholder="Ex : Chrome Mac Studio, Personal MacBook…"
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
                  Format : <code className="font-mono">ely_ext_</code> + 48 caractères
                  hex (192 bits d’entropie). Pas de date d’expiration.
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

              {/* List */}
              <section>
                <h2 className="font-medium mb-3">Vos tokens</h2>
                {loading ? (
                  <div className="text-sm text-[var(--text-2)] flex items-center gap-2">
                    <Loader2 size={14} className="animate-spin" /> Chargement…
                  </div>
                ) : tokens.length === 0 ? (
                  <div className="rounded-lg border border-dashed border-[var(--border)] p-6 text-center text-sm text-[var(--text-2)]">
                    Aucun token. Générez-en un ci-dessus pour relier votre
                    extension Chrome.
                  </div>
                ) : (
                  <ul className="space-y-2">
                    {tokens.map((tok) => (
                      <li
                        key={tok.id}
                        className={`rounded-lg border p-3 flex items-center gap-3 ${
                          tok.revoked
                            ? "border-[var(--border)] bg-[var(--bg-2)] opacity-60"
                            : "border-[var(--border)] bg-[var(--bg-2)]"
                        }`}
                      >
                        <div className="flex-1 min-w-0">
                          <div className="flex items-center gap-2 flex-wrap">
                            <span className="font-medium truncate">{tok.name}</span>
                            <span className="font-mono text-xs text-[var(--text-3)]">
                              …{tok.last_4}
                            </span>
                            {tok.revoked && (
                              <span
                                className="inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded"
                                style={{
                                  background: "rgba(239, 68, 68, 0.15)",
                                  color: "rgb(248, 113, 113)",
                                  border: "1px solid rgba(239, 68, 68, 0.35)",
                                }}
                              >
                                <ShieldOff size={11} /> révoqué
                              </span>
                            )}
                          </div>
                          <div className="text-xs text-[var(--text-3)] mt-1 flex flex-wrap gap-x-4 gap-y-0.5">
                            <span className="inline-flex items-center gap-1">
                              <Clock size={11} /> Créé {formatDate(tok.created_at)}
                            </span>
                            <span>
                              Dernière utilisation : {formatDate(tok.last_used_at)}
                            </span>
                          </div>
                        </div>
                        {!tok.revoked && (
                          <button
                            type="button"
                            onClick={() => handleRevoke(tok.id, tok.name)}
                            disabled={revokingId === tok.id}
                            className="revoke-btn px-3 py-1.5 rounded inline-flex items-center gap-1.5 text-sm disabled:opacity-50"
                            style={{
                              background: "transparent",
                              border: "1px solid var(--border)",
                              color: "var(--text)",
                            }}
                            title="Révoquer ce token"
                          >
                            {revokingId === tok.id ? (
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
                  <strong>Comment l’utiliser :</strong> ouvrez l’extension ELY
                  dans Chrome → bouton « Options » → collez ce token dans le
                  champ « Token longue durée ». L’extension se reconnectera
                  automatiquement à chaque redémarrage du navigateur, sans
                  jamais nécessiter d’ouvrir DevTools.
                </p>
                <p>
                  <strong>Sécurité :</strong> seul le hash SHA-256 du token est
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
