"use client";

import { useState, useEffect } from "react";
import { AuthGuard } from "@/components/layout/AuthGuard";
import { Sidebar } from "@/components/layout/Sidebar";
import { Header } from "@/components/layout/Header";
import { Cpu, Key, Server, Info, ShieldCheck, Mail, Calendar, HardDrive, CheckCircle, XCircle, ExternalLink } from "lucide-react";
import { authFetch } from "@/lib/auth";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

const PROVIDERS = [
  {
    id: "anthropic",
    label: "Anthropic Claude",
    flag: "🇺🇸",
    desc: "Fiable, rapide — serveurs aux États-Unis",
    tier: "B/C",
    models: ["claude-haiku-4-5-20251001", "claude-sonnet-4-5", "claude-opus-4-5"],
    envKey: "ANTHROPIC_API_KEY",
    docsUrl: "https://console.anthropic.com/",
  },
  {
    id: "mistral",
    label: "Mistral AI",
    flag: "🇫🇷",
    desc: "IA française, serveurs en Europe (RGPD), coûts raisonnables",
    tier: "B",
    models: ["mistral-small-latest", "mistral-medium-latest", "mistral-large-latest"],
    envKey: "MISTRAL_API_KEY",
    docsUrl: "https://console.mistral.ai/",
    rgpd: true,
  },
  {
    id: "ollama",
    label: "Ollama (Local)",
    flag: "🖥️",
    desc: "100 % local, zéro données transmises — nécessite un GPU",
    tier: "A",
    models: ["llama3.2", "qwen2.5-coder", "mistral"],
    envKey: null,
    docsUrl: "https://ollama.com/",
    rgpd: true,
  },
  {
    id: "deepseek",
    label: "DeepSeek",
    flag: "🇨🇳",
    desc: "Coût très faible — serveurs en Chine",
    tier: "C",
    models: ["deepseek-chat", "deepseek-reasoner"],
    envKey: "DEEPSEEK_API_KEY",
    docsUrl: "https://platform.deepseek.com/",
  },
];

const API_KEYS = [
  { key: "ANTHROPIC_API_KEY", desc: "Requis pour Anthropic Claude" },
  { key: "MISTRAL_API_KEY",   desc: "Requis pour Mistral AI" },
  { key: "DEEPSEEK_API_KEY",  desc: "Requis pour DeepSeek" },
  { key: "JWT_SECRET_KEY",    desc: "Obligatoire — générer une chaîne aléatoire de 32+ caractères" },
];

const GOOGLE_SERVICES = [
  { id: "gmail",    label: "Gmail",          icon: Mail,        scope: "Lecture et envoi d'emails" },
  { id: "calendar", label: "Google Calendar", icon: Calendar,    scope: "Consultation et création d'événements" },
  { id: "drive",    label: "Google Drive",    icon: HardDrive,   scope: "Lecture des fichiers (lecture seule)" },
];

export default function SettingsPage() {
  const [activeProvider, setActiveProvider] = useState("anthropic");
  const [googleConnected, setGoogleConnected] = useState<boolean | null>(null);
  const [googleLoading, setGoogleLoading] = useState(false);
  const active = PROVIDERS.find((p) => p.id === activeProvider)!;

  // Check Google connection status
  useEffect(() => {
    authFetch(`${API_URL}/google/status`)
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

  const handleGoogleConnect = async () => {
    setGoogleLoading(true);
    try {
      const res = await authFetch(`${API_URL}/google/auth-url`);
      const { url } = await res.json();
      window.location.href = url;
    } catch {
      alert("Erreur lors de la connexion Google. Vérifiez que GOOGLE_CLIENT_ID et GOOGLE_CLIENT_SECRET sont configurés dans le .env.");
    } finally {
      setGoogleLoading(false);
    }
  };

  const handleGoogleDisconnect = async () => {
    setGoogleLoading(true);
    try {
      await authFetch(`${API_URL}/google/disconnect`, { method: "DELETE" });
      setGoogleConnected(false);
    } finally {
      setGoogleLoading(false);
    }
  };

  return (
    <AuthGuard>
      <div className="flex h-screen overflow-hidden">
        <Sidebar />
        <div className="flex flex-col flex-1 overflow-hidden">
          <Header />
          <div className="flex-1 overflow-y-auto p-6 space-y-6 max-w-2xl">

            {/* LLM Provider */}
            <section>
              <div className="flex items-center gap-2 mb-4">
                <Cpu className="w-4 h-4 text-cyber-cyan" />
                <h2 className="text-sm font-medium text-text-primary">Fournisseur LLM</h2>
              </div>

              <div className="space-y-2">
                {PROVIDERS.map((p) => {
                  const isActive = activeProvider === p.id;
                  return (
                    <button
                      key={p.id}
                      onClick={() => setActiveProvider(p.id)}
                      className={`w-full flex items-center justify-between p-4 rounded-lg border text-left transition-all ${
                        isActive
                          ? "bg-cyber-cyan/5 border-cyber-cyan/30 text-text-primary"
                          : "bg-bg-secondary border-border-dim text-text-secondary hover:border-text-muted"
                      }`}
                    >
                      <div className="flex items-start gap-3 min-w-0">
                        <span className="text-base mt-0.5 shrink-0">{p.flag}</span>
                        <div className="min-w-0">
                          <div className="flex items-center gap-2">
                            <span className="text-sm font-medium">{p.label}</span>
                            {p.rgpd && (
                              <span className="inline-flex items-center gap-0.5 text-[9px] px-1.5 py-0.5 rounded bg-emerald-500/10 border border-emerald-500/20 text-emerald-400 shrink-0">
                                <ShieldCheck className="w-2.5 h-2.5" />
                                RGPD
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

              {/* Selected provider details */}
              <div className="mt-4 bg-bg-secondary border border-border-dim rounded-lg p-4 space-y-3">
                <div className="flex items-center justify-between">
                  <span className="text-xs text-text-muted uppercase tracking-wider">Modèles disponibles</span>
                  <a
                    href={active.docsUrl}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-[10px] text-cyber-cyan hover:underline"
                  >
                    Console →
                  </a>
                </div>
                <div className="flex flex-wrap gap-1.5">
                  {active.models.map((m) => (
                    <code key={m} className="text-[11px] px-2 py-0.5 rounded bg-bg-primary border border-border-dim text-text-secondary">
                      {m}
                    </code>
                  ))}
                </div>

                <p className="text-[11px] text-text-muted flex items-start gap-1.5 pt-1 border-t border-border-dim">
                  <Info className="w-3 h-3 shrink-0 mt-0.5" />
                  Configurer via{" "}
                  <code className="text-cyber-cyan">ACTIVE_LLM_PROVIDER={active.id}</code>
                  {" "}et{" "}
                  <code className="text-cyber-cyan">ACTIVE_LLM_MODEL=…</code>
                  {" "}dans le fichier <code className="text-cyber-cyan">.env</code>.
                </p>
              </div>
            </section>

            {/* API Keys */}
            <section>
              <div className="flex items-center gap-2 mb-4">
                <Key className="w-4 h-4 text-cyber-cyan" />
                <h2 className="text-sm font-medium text-text-primary">Clés API</h2>
              </div>
              <div className="bg-bg-secondary border border-border-dim rounded-lg p-4 space-y-3">
                {API_KEYS.map((item) => (
                  <div key={item.key} className="flex items-start gap-3">
                    <code className="text-xs text-cyber-cyan bg-cyber-cyan/5 border border-cyber-cyan/20 rounded px-2 py-1 shrink-0">
                      {item.key}
                    </code>
                    <span className="text-xs text-text-muted pt-1">{item.desc}</span>
                  </div>
                ))}
              </div>
              <p className="text-xs text-text-muted mt-2">
                À définir dans <code className="text-cyber-cyan">backend/.env</code>
              </p>
            </section>

            {/* Google Services */}
            <section>
              <div className="flex items-center gap-2 mb-4">
                <div className="w-4 h-4 text-cyber-cyan">G</div>
                <h2 className="text-sm font-medium text-text-primary">Services Google</h2>
                {googleConnected === true && (
                  <span className="inline-flex items-center gap-1 text-[9px] px-1.5 py-0.5 rounded bg-emerald-500/10 border border-emerald-500/20 text-emerald-400">
                    <CheckCircle className="w-2.5 h-2.5" /> Connecté
                  </span>
                )}
                {googleConnected === false && (
                  <span className="inline-flex items-center gap-1 text-[9px] px-1.5 py-0.5 rounded bg-text-muted/10 border border-border-dim text-text-muted">
                    <XCircle className="w-2.5 h-2.5" /> Non connecté
                  </span>
                )}
              </div>

              <div className="bg-bg-secondary border border-border-dim rounded-lg p-4 space-y-4">
                {/* Services list */}
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

                {/* Security notice */}
                <p className="text-[11px] text-text-muted flex items-start gap-1.5 pt-2 border-t border-border-dim">
                  <ShieldCheck className="w-3 h-3 shrink-0 mt-0.5 text-emerald-400" />
                  ELY n'accède à ces services que sur demande explicite. Un token OAuth2 est stocké localement — aucune donnée ne transite par un serveur tiers.
                </p>

                {/* Connect / Disconnect */}
                <div className="pt-1">
                  {googleConnected ? (
                    <button
                      onClick={handleGoogleDisconnect}
                      disabled={googleLoading}
                      className="text-xs px-3 py-1.5 rounded border border-cyber-red/30 text-cyber-red hover:bg-cyber-red/5 transition-all disabled:opacity-50"
                    >
                      {googleLoading ? "..." : "Déconnecter Google"}
                    </button>
                  ) : (
                    <button
                      onClick={handleGoogleConnect}
                      disabled={googleLoading}
                      className="inline-flex items-center gap-2 text-xs px-3 py-1.5 rounded border border-cyber-cyan/30 text-cyber-cyan hover:bg-cyber-cyan/5 transition-all disabled:opacity-50"
                    >
                      <ExternalLink className="w-3 h-3" />
                      {googleLoading ? "Redirection..." : "Connecter mon compte Google"}
                    </button>
                  )}
                </div>

                {/* Setup instructions if not configured */}
                <details className="text-[11px] text-text-muted">
                  <summary className="cursor-pointer hover:text-text-secondary">Comment configurer ?</summary>
                  <ol className="mt-2 space-y-1 pl-3 list-decimal">
                    <li>Aller sur <a href="https://console.cloud.google.com/" target="_blank" rel="noopener noreferrer" className="text-cyber-cyan hover:underline">console.cloud.google.com</a></li>
                    <li>Créer un projet → API &amp; Services → Identifiants</li>
                    <li>Créer un ID client OAuth 2.0 (application Web)</li>
                    <li>Ajouter l'URI de redirection autorisée : <code className="text-cyber-cyan">http://localhost:8000/google/callback</code></li>
                    <li>Copier le Client ID et Secret dans <code className="text-cyber-cyan">.env</code> :<br/>
                      <code className="text-cyber-cyan">GOOGLE_CLIENT_ID=…</code><br/>
                      <code className="text-cyber-cyan">GOOGLE_CLIENT_SECRET=…</code>
                    </li>
                    <li>Redémarrer le backend (<code className="text-cyber-cyan">./start.sh restart</code>)</li>
                  </ol>
                </details>
              </div>
            </section>

            {/* SSH Hosts */}
            <section>
              <div className="flex items-center gap-2 mb-4">
                <Server className="w-4 h-4 text-cyber-cyan" />
                <h2 className="text-sm font-medium text-text-primary">Hôtes SSH</h2>
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

          </div>
        </div>
      </div>
    </AuthGuard>
  );
}
