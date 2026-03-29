"use client";

import { useState, useEffect, useCallback } from "react";
import { AuthGuard } from "@/components/layout/AuthGuard";
import { Sidebar } from "@/components/layout/Sidebar";
import { Header } from "@/components/layout/Header";
import {
  Cpu, Key, Server, ShieldCheck, Mail, Calendar, HardDrive,
  CheckCircle, XCircle, ExternalLink, Check, AlertCircle, Languages,
} from "lucide-react";
import { authFetch, isAdmin } from "@/lib/auth";
import { useTranslations } from "next-intl";
import { setLocale } from "@/lib/locale";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

// ---------------------------------------------------------------------------
// Provider catalogue (UI-side)
// ---------------------------------------------------------------------------
const PROVIDERS = [
  {
    id: "anthropic",
    label: "Anthropic Claude",
    flag: "🇺🇸",
    desc: "Fiable, rapide — serveurs aux États-Unis",
    tier: "B/C",
    docsUrl: "https://console.anthropic.com/",
  },
  {
    id: "mistral",
    label: "Mistral AI",
    flag: "🇫🇷",
    desc: "IA française, serveurs en Europe (RGPD), coûts raisonnables",
    tier: "B",
    docsUrl: "https://console.mistral.ai/",
    rgpd: true,
  },
  {
    id: "ollama",
    label: "Ollama (Local)",
    flag: "🖥️",
    desc: "100 % local, zéro données transmises — nécessite un GPU",
    tier: "A",
    docsUrl: "https://ollama.com/",
    rgpd: true,
  },
  {
    id: "deepseek",
    label: "DeepSeek",
    flag: "🇨🇳",
    desc: "Coût très faible — serveurs en Chine",
    tier: "C",
    docsUrl: "https://platform.deepseek.com/",
  },
  {
    id: "gemini",
    label: "Google Gemini",
    flag: "🇺🇸",
    desc: "Gemini 2.0 Flash / Pro",
    tier: "B",
    docsUrl: "https://aistudio.google.com/",
  },
];

const GOOGLE_SERVICES = [
  { id: "gmail",    label: "Gmail",          icon: Mail,     scope: "Lecture et envoi d'emails" },
  { id: "calendar", label: "Google Calendar", icon: Calendar, scope: "Consultation et création d'événements" },
  { id: "drive",    label: "Google Drive",    icon: HardDrive, scope: "Lecture des fichiers (lecture seule)" },
];

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------
interface ProviderMeta {
  id: string;
  name: string;
  models: string[];
  has_key: boolean;
}

interface LLMSettings {
  provider: string;
  model: string;
  providers: ProviderMeta[];
}

type ToastKind = "success" | "error";
interface Toast {
  id: number;
  kind: ToastKind;
  message: string;
}

// ---------------------------------------------------------------------------
// Small toast hook
// ---------------------------------------------------------------------------
let _toastCounter = 0;

function useToasts() {
  const [toasts, setToasts] = useState<Toast[]>([]);

  const push = useCallback((kind: ToastKind, message: string) => {
    const id = ++_toastCounter;
    setToasts((prev) => [...prev, { id, kind, message }]);
    setTimeout(() => setToasts((prev) => prev.filter((t) => t.id !== id)), 3500);
  }, []);

  return { toasts, push };
}

// ---------------------------------------------------------------------------
// Page component
// ---------------------------------------------------------------------------
export default function SettingsPage() {
  const t = useTranslations("settings");
  const tc = useTranslations("common");
  const admin = isAdmin();

  // LLM state
  const [llmLoaded, setLlmLoaded]         = useState(false);
  const [activeProvider, setActiveProvider] = useState("anthropic");
  const [activeModel, setActiveModel]       = useState("");
  const [providersMeta, setProvidersMeta]   = useState<ProviderMeta[]>([]);
  const [apiKeyInput, setApiKeyInput]       = useState("");
  const [savingLLM, setSavingLLM]           = useState(false);
  const [savingKey, setSavingKey]           = useState(false);

  // Google state
  const [googleConnected, setGoogleConnected] = useState<boolean | null>(null);
  const [googleLoading, setGoogleLoading]     = useState(false);

  const { toasts, push } = useToasts();

  // Derived: current provider metadata from the API response
  const currentMeta = providersMeta.find((p) => p.id === activeProvider);
  const uiProvider  = PROVIDERS.find((p) => p.id === activeProvider);
  const models      = currentMeta?.models ?? [];

  // ---------------------------------------------------------------------------
  // Load LLM settings from API
  // ---------------------------------------------------------------------------
  const loadLLMSettings = useCallback(async () => {
    try {
      const res = await authFetch(`${API_URL}/api/settings/llm`);
      if (!res.ok) return;
      const data: LLMSettings = await res.json();
      setActiveProvider(data.provider);
      setActiveModel(data.model);
      setProvidersMeta(data.providers);
      setLlmLoaded(true);
    } catch {
      // silently ignore — env defaults remain
    }
  }, []);

  useEffect(() => {
    loadLLMSettings();
  }, [loadLLMSettings]);

  // Clear key input whenever provider changes
  useEffect(() => {
    setApiKeyInput("");
  }, [activeProvider]);

  // Check Google connection status
  useEffect(() => {
    authFetch(`${API_URL}/api/google/status`)
      .then((r) => r.json())
      .then((d) => setGoogleConnected(d.connected))
      .catch(() => setGoogleConnected(false));
  }, []);

  // Handle ?google=connected redirect from OAuth callback
  useEffect(() => {
    if (typeof window !== "undefined" && window.location.search.includes("google=connected")) {
      setGoogleConnected(true);
      window.history.replaceState({}, "", "/settings");
    }
  }, []);

  // ---------------------------------------------------------------------------
  // Handlers — LLM
  // ---------------------------------------------------------------------------
  const handleProviderClick = async (providerId: string) => {
    if (!admin || savingLLM) return;
    const meta = providersMeta.find((p) => p.id === providerId);
    const defaultModel = meta?.models[0] ?? "";

    setActiveProvider(providerId);
    setActiveModel(defaultModel);
    setSavingLLM(true);
    try {
      const res = await authFetch(`${API_URL}/api/settings/llm`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ provider: providerId, model: defaultModel }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        push("error", err.detail ?? `Erreur ${res.status}`);
      } else {
        push("success", "Fournisseur sauvegardé");
      }
    } catch {
      push("error", "Impossible de contacter le serveur");
    } finally {
      setSavingLLM(false);
    }
  };

  const handleModelChange = async (model: string) => {
    if (!admin || savingLLM) return;
    setActiveModel(model);
    setSavingLLM(true);
    try {
      const res = await authFetch(`${API_URL}/api/settings/llm`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ provider: activeProvider, model }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        push("error", err.detail ?? `Erreur ${res.status}`);
      } else {
        push("success", "Modèle sauvegardé");
      }
    } catch {
      push("error", "Impossible de contacter le serveur");
    } finally {
      setSavingLLM(false);
    }
  };

  const handleSaveKey = async () => {
    if (!admin || savingKey || !apiKeyInput.trim()) return;
    setSavingKey(true);
    try {
      const res = await authFetch(`${API_URL}/api/settings/llm/keys/${activeProvider}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ api_key: apiKeyInput.trim() }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        push("error", err.detail ?? `Erreur ${res.status}`);
      } else {
        push("success", "Clé API sauvegardée");
        setApiKeyInput("");
        // Refresh metadata so has_key badge updates
        await loadLLMSettings();
      }
    } catch {
      push("error", "Impossible de contacter le serveur");
    } finally {
      setSavingKey(false);
    }
  };

  // ---------------------------------------------------------------------------
  // Handlers — Google
  // ---------------------------------------------------------------------------
  const handleGoogleConnect = async () => {
    setGoogleLoading(true);
    try {
      const res = await authFetch(`${API_URL}/api/google/auth-url`);
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || `Erreur serveur ${res.status}`);
      if (!data.url) throw new Error("URL de connexion Google non reçue du serveur");
      window.location.href = data.url;
    } catch (e) {
      alert(e instanceof Error ? e.message : "Erreur lors de la connexion Google.");
    } finally {
      setGoogleLoading(false);
    }
  };

  const handleGoogleDisconnect = async () => {
    setGoogleLoading(true);
    try {
      await authFetch(`${API_URL}/api/google/disconnect`, { method: "DELETE" });
      setGoogleConnected(false);
    } finally {
      setGoogleLoading(false);
    }
  };

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------
  const needsKey = activeProvider !== "ollama";
  const hasKey   = currentMeta?.has_key ?? false;

  return (
    <AuthGuard>
      <div className="flex h-screen overflow-hidden">
        <Sidebar />
        <div className="flex flex-col flex-1 overflow-hidden">
          <Header />

          {/* Toast stack */}
          <div className="fixed bottom-6 right-6 z-50 flex flex-col gap-2 pointer-events-none">
            {toasts.map((t) => (
              <div
                key={t.id}
                className={`flex items-center gap-2 px-4 py-2.5 rounded-lg border text-xs shadow-lg pointer-events-auto transition-all ${
                  t.kind === "success"
                    ? "bg-emerald-900/80 border-emerald-500/30 text-emerald-300"
                    : "bg-red-900/80 border-red-500/30 text-red-300"
                }`}
              >
                {t.kind === "success"
                  ? <Check className="w-3.5 h-3.5 shrink-0" />
                  : <AlertCircle className="w-3.5 h-3.5 shrink-0" />}
                {t.message}
              </div>
            ))}
          </div>

          <div className="flex-1 overflow-y-auto p-6 space-y-6 max-w-2xl">

            {/* ----------------------------------------------------------------
                LLM Provider — admin only
            ---------------------------------------------------------------- */}
            {admin && (
              <section>
                <div className="flex items-center gap-2 mb-4">
                  <Cpu className="w-4 h-4 text-cyber-cyan" />
                  <h2 className="text-sm font-medium text-text-primary">{t("llmProvider")}</h2>
                  {savingLLM && (
                    <span className="text-[10px] text-text-muted animate-pulse">{tc("saving")}</span>
                  )}
                </div>

                {/* Provider cards */}
                <div className="space-y-2">
                  {PROVIDERS.map((p) => {
                    const isActive = activeProvider === p.id;
                    const meta = providersMeta.find((m) => m.id === p.id);
                    return (
                      <button
                        key={p.id}
                        onClick={() => handleProviderClick(p.id)}
                        disabled={savingLLM}
                        className={`w-full flex items-center justify-between p-4 rounded-lg border text-left transition-all disabled:opacity-60 ${
                          isActive
                            ? "bg-cyber-cyan/5 border-cyber-cyan/30 text-text-primary"
                            : "bg-bg-secondary border-border-dim text-text-secondary hover:border-text-muted"
                        }`}
                      >
                        <div className="flex items-start gap-3 min-w-0">
                          <span className="text-base mt-0.5 shrink-0">{p.flag}</span>
                          <div className="min-w-0">
                            <div className="flex items-center gap-2 flex-wrap">
                              <span className="text-sm font-medium">{p.label}</span>
                              {p.rgpd && (
                                <span className="inline-flex items-center gap-0.5 text-[9px] px-1.5 py-0.5 rounded bg-emerald-500/10 border border-emerald-500/20 text-emerald-400 shrink-0">
                                  <ShieldCheck className="w-2.5 h-2.5" />
                                  RGPD
                                </span>
                              )}
                              {llmLoaded && meta && meta.has_key && p.id !== "ollama" && (
                                <span className="inline-flex items-center gap-0.5 text-[9px] px-1.5 py-0.5 rounded bg-emerald-500/10 border border-emerald-500/20 text-emerald-400 shrink-0">
                                  <Check className="w-2.5 h-2.5" />
                                  {t("keyConfigured")}
                                </span>
                              )}
                            </div>
                            <div className="text-xs text-text-muted mt-0.5">{p.desc}</div>
                          </div>
                        </div>
                        <span className={`text-[10px] px-2 py-0.5 rounded border shrink-0 ml-3 ${
                          isActive
                            ? "bg-cyber-cyan/10 border-cyber-cyan/30 text-cyber-cyan"
                            : "bg-bg-primary border-border-dim text-text-muted"
                        }`}>
                          Tier {p.tier}
                        </span>
                      </button>
                    );
                  })}
                </div>

                {/* Model selector + API key input */}
                <div className="mt-4 bg-bg-secondary border border-border-dim rounded-lg p-4 space-y-4">

                  {/* Model selector */}
                  <div className="space-y-1.5">
                    <div className="flex items-center justify-between">
                      <span className="text-xs text-text-muted uppercase tracking-wider">{t("activeModel")}</span>
                      {uiProvider && (
                        <a
                          href={uiProvider.docsUrl}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="text-[10px] text-cyber-cyan hover:underline"
                        >
                          Console →
                        </a>
                      )}
                    </div>
                    {models.length > 0 ? (
                      <select
                        value={activeModel}
                        onChange={(e) => handleModelChange(e.target.value)}
                        disabled={savingLLM}
                        className="w-full text-xs bg-bg-primary border border-border-dim rounded px-3 py-2 text-text-primary focus:outline-none focus:border-cyber-cyan/40 disabled:opacity-60"
                      >
                        {models.map((m) => (
                          <option key={m} value={m}>{m}</option>
                        ))}
                      </select>
                    ) : (
                      <div className="flex flex-wrap gap-1.5">
                        {PROVIDERS.find((p) => p.id === activeProvider) &&
                          <code className="text-[11px] px-2 py-0.5 rounded bg-bg-primary border border-border-dim text-text-secondary">
                            {activeModel}
                          </code>
                        }
                      </div>
                    )}
                  </div>

                  {/* API key section */}
                  {needsKey && (
                    <div className="space-y-2 pt-3 border-t border-border-dim">
                      <div className="flex items-center gap-2">
                        <Key className="w-3.5 h-3.5 text-cyber-cyan" />
                        <span className="text-xs text-text-muted uppercase tracking-wider">{t("apiKey")}</span>
                        {hasKey && (
                          <span className="inline-flex items-center gap-0.5 text-[9px] px-1.5 py-0.5 rounded bg-emerald-500/10 border border-emerald-500/20 text-emerald-400">
                            <Check className="w-2.5 h-2.5" />
                            {t("keyConfigured")}
                          </span>
                        )}
                      </div>
                      <div className="flex gap-2">
                        <input
                          type="password"
                          value={apiKeyInput}
                          onChange={(e) => setApiKeyInput(e.target.value)}
                          placeholder="sk-••••••••"
                          autoComplete="new-password"
                          className="flex-1 text-xs bg-bg-primary border border-border-dim rounded px-3 py-2 text-text-primary placeholder:text-text-muted focus:outline-none focus:border-cyber-cyan/40"
                        />
                        <button
                          onClick={handleSaveKey}
                          disabled={savingKey || !apiKeyInput.trim()}
                          className="text-xs px-3 py-2 rounded border border-cyber-cyan/30 text-cyber-cyan hover:bg-cyber-cyan/5 transition-all disabled:opacity-40 shrink-0"
                        >
                          {savingKey ? "…" : tc("save")}
                        </button>
                      </div>
                      <p className="text-[10px] text-text-muted">
                        {t("keyStoredEncrypted")}
                      </p>
                    </div>
                  )}
                </div>
              </section>
            )}

            {/* ----------------------------------------------------------------
                Google Services — visible by all authenticated users
            ---------------------------------------------------------------- */}
            <section>
              <div className="flex items-center gap-2 mb-4">
                <div className="w-4 h-4 text-cyber-cyan font-bold text-sm">G</div>
                <h2 className="text-sm font-medium text-text-primary">{t("googleServices")}</h2>
                {googleConnected === true && (
                  <span className="inline-flex items-center gap-1 text-[9px] px-1.5 py-0.5 rounded bg-emerald-500/10 border border-emerald-500/20 text-emerald-400">
                    <CheckCircle className="w-2.5 h-2.5" /> {tc("connected")}
                  </span>
                )}
                {googleConnected === false && (
                  <span className="inline-flex items-center gap-1 text-[9px] px-1.5 py-0.5 rounded bg-text-muted/10 border border-border-dim text-text-muted">
                    <XCircle className="w-2.5 h-2.5" /> {tc("disconnected")}
                  </span>
                )}
              </div>

              <div className="bg-bg-secondary border border-border-dim rounded-lg p-4 space-y-4">
                <div className="space-y-2">
                  {GOOGLE_SERVICES.map(({ id, label, icon: Icon, scope }) => (
                    <div key={id} className="flex items-center gap-3">
                      <div className={`w-7 h-7 rounded flex items-center justify-center shrink-0 ${
                        googleConnected ? "bg-emerald-500/10 border border-emerald-500/20" : "bg-bg-primary border border-border-dim"
                      }`}>
                        <Icon className={`w-3.5 h-3.5 ${googleConnected ? "text-emerald-400" : "text-text-muted"}`} />
                      </div>
                      <div>
                        <div className="text-xs font-medium text-text-primary">{label}</div>
                        <div className="text-[11px] text-text-muted">{scope}</div>
                      </div>
                    </div>
                  ))}
                </div>

                <p className="text-[11px] text-text-muted flex items-start gap-1.5 pt-2 border-t border-border-dim">
                  <ShieldCheck className="w-3 h-3 shrink-0 mt-0.5 text-emerald-400" />
                  ELY n'accède à ces services que sur demande explicite. Un token OAuth2 est stocké localement — aucune donnée ne transite par un serveur tiers.
                </p>

                <div className="pt-1">
                  {googleConnected ? (
                    <button
                      onClick={handleGoogleDisconnect}
                      disabled={googleLoading}
                      className="text-xs px-3 py-1.5 rounded border border-cyber-red/30 text-cyber-red hover:bg-cyber-red/5 transition-all disabled:opacity-50"
                    >
                      {googleLoading ? "..." : t("disconnectGoogle")}
                    </button>
                  ) : (
                    <button
                      onClick={handleGoogleConnect}
                      disabled={googleLoading}
                      className="inline-flex items-center gap-2 text-xs px-3 py-1.5 rounded border border-cyber-cyan/30 text-cyber-cyan hover:bg-cyber-cyan/5 transition-all disabled:opacity-50"
                    >
                      <ExternalLink className="w-3 h-3" />
                      {googleLoading ? tc("redirecting") : t("connectGoogle")}
                    </button>
                  )}
                </div>

                <details className="text-[11px] text-text-muted">
                  <summary className="cursor-pointer hover:text-text-secondary">{t("howToConfigure")}</summary>
                  <ol className="mt-2 space-y-1 pl-3 list-decimal">
                    <li>Aller sur <a href="https://console.cloud.google.com/" target="_blank" rel="noopener noreferrer" className="text-cyber-cyan hover:underline">console.cloud.google.com</a></li>
                    <li>Créer un projet → API &amp; Services → Identifiants</li>
                    <li>Créer un ID client OAuth 2.0 (application Web)</li>
                    <li>Ajouter l'URI de redirection : <code className="text-cyber-cyan">http://localhost:8000/api/google/callback</code></li>
                    <li>Renseigner le Client ID et Secret dans <a href="/admin" className="text-cyber-cyan hover:underline">Admin → OAuth Google</a> (sans redémarrage)</li>
                    <li>Revenir ici et cliquer sur "Connecter mon compte Google"</li>
                  </ol>
                </details>
              </div>
            </section>

            {/* ----------------------------------------------------------------
                Language
            ---------------------------------------------------------------- */}
            <section>
              <div className="flex items-center gap-2 mb-4">
                <Languages className="w-4 h-4 text-cyber-cyan" />
                <h2 className="text-sm font-medium text-text-primary">{t("language")}</h2>
              </div>
              <div className="bg-bg-secondary border border-border-dim rounded-lg p-4 space-y-3">
                <p className="text-xs text-text-muted">{t("languageDescription")}</p>
                <div className="flex gap-2">
                  <button
                    onClick={() => setLocale("fr")}
                    className="text-xs px-3 py-1.5 rounded border border-cyber-cyan/30 text-cyber-cyan hover:bg-cyber-cyan/5 transition-all"
                  >
                    {t("french")}
                  </button>
                  <button
                    onClick={() => setLocale("en")}
                    className="text-xs px-3 py-1.5 rounded border border-cyber-cyan/30 text-cyber-cyan hover:bg-cyber-cyan/5 transition-all"
                  >
                    {t("english")}
                  </button>
                </div>
              </div>
            </section>

            {/* ----------------------------------------------------------------
                SSH Hosts — admin only
            ---------------------------------------------------------------- */}
            {admin && (
              <section>
                <div className="flex items-center gap-2 mb-4">
                  <Server className="w-4 h-4 text-cyber-cyan" />
                  <h2 className="text-sm font-medium text-text-primary">{t("sshHosts")}</h2>
                </div>
                <div className="bg-bg-secondary border border-border-dim rounded-lg p-4">
                  <p className="text-xs text-text-muted">
                    Configurer les hôtes SSH et leurs commandes autorisées dans{" "}
                    <code className="text-cyber-cyan">config/hosts.yaml</code>.
                    Chaque hôte requiert une liste explicite de commandes — l'agent ne peut pas
                    exécuter de commandes arbitraires.
                  </p>
                  <pre className="mt-3 text-[11px] text-text-secondary bg-bg-primary border border-border-dim rounded p-3 overflow-x-auto">
{`hosts:
  my-server:
    hostname: 192.168.1.100
    port: 22
    username: ubuntu
    key_file: ~/.ssh/id_rsa
    allowed_commands:
      - "df -h"
      - "docker ps"
      - "systemctl status *"`}
                  </pre>
                </div>
              </section>
            )}

          </div>
        </div>
      </div>
    </AuthGuard>
  );
}
