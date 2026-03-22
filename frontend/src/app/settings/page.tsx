"use client";

import { useState } from "react";
import { AuthGuard } from "@/components/layout/AuthGuard";
import { Sidebar } from "@/components/layout/Sidebar";
import { Header } from "@/components/layout/Header";
import { Cpu, Key, Server, Info, ShieldCheck } from "lucide-react";

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

export default function SettingsPage() {
  const [activeProvider, setActiveProvider] = useState("anthropic");
  const active = PROVIDERS.find((p) => p.id === activeProvider)!;

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
