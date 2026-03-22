"use client";

import { useState } from "react";
import { AuthGuard } from "@/components/layout/AuthGuard";
import { Sidebar } from "@/components/layout/Sidebar";
import { Header } from "@/components/layout/Header";
import { Cpu, Key, Server, Info } from "lucide-react";

const PROVIDERS = [
  { id: "anthropic", label: "Anthropic Claude", desc: "Recommended — reliable, fast, private", tier: "B/C" },
  { id: "ollama", label: "Ollama (Local)", desc: "100% local, requires GPU", tier: "A" },
  { id: "deepseek", label: "DeepSeek", desc: "Low cost, China-hosted", tier: "B" },
];

export default function SettingsPage() {
  const [activeProvider, setActiveProvider] = useState("anthropic");

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
                <h2 className="text-sm font-medium text-text-primary">LLM Provider</h2>
              </div>
              <div className="space-y-2">
                {PROVIDERS.map((p) => (
                  <button
                    key={p.id}
                    onClick={() => setActiveProvider(p.id)}
                    className={`w-full flex items-center justify-between p-4 rounded-lg border text-left transition-all ${
                      activeProvider === p.id
                        ? "bg-cyber-cyan/5 border-cyber-cyan/30 text-text-primary"
                        : "bg-bg-secondary border-border-dim text-text-secondary hover:border-text-muted"
                    }`}
                  >
                    <div>
                      <div className="text-sm font-medium">{p.label}</div>
                      <div className="text-xs text-text-muted mt-0.5">{p.desc}</div>
                    </div>
                    <span className={`text-[10px] px-2 py-0.5 rounded border ${
                      activeProvider === p.id
                        ? "bg-cyber-cyan/10 border-cyber-cyan/30 text-cyber-cyan"
                        : "bg-bg-primary border-border-dim text-text-muted"
                    }`}>
                      Tier {p.tier}
                    </span>
                  </button>
                ))}
              </div>
              <p className="text-xs text-text-muted mt-3 flex items-start gap-1.5">
                <Info className="w-3.5 h-3.5 shrink-0 mt-0.5" />
                Switch provider in <code className="text-cyber-cyan">config/providers.yaml</code> or via the <code className="text-cyber-cyan">ACTIVE_LLM_PROVIDER</code> env variable.
              </p>
            </section>

            {/* API Keys info */}
            <section>
              <div className="flex items-center gap-2 mb-4">
                <Key className="w-4 h-4 text-cyber-cyan" />
                <h2 className="text-sm font-medium text-text-primary">API Keys</h2>
              </div>
              <div className="bg-bg-secondary border border-border-dim rounded-lg p-4 space-y-3">
                {[
                  { key: "ANTHROPIC_API_KEY", desc: "Required for Claude (Option B/C)" },
                  { key: "DEEPSEEK_API_KEY", desc: "Required for DeepSeek provider" },
                  { key: "JWT_SECRET_KEY", desc: "Required — generate a random 32+ char secret" },
                ].map((item) => (
                  <div key={item.key} className="flex items-start gap-3">
                    <code className="text-xs text-cyber-cyan bg-cyber-cyan/5 border border-cyber-cyan/20 rounded px-2 py-1 shrink-0">
                      {item.key}
                    </code>
                    <span className="text-xs text-text-muted pt-1">{item.desc}</span>
                  </div>
                ))}
              </div>
              <p className="text-xs text-text-muted mt-2">Set these in <code className="text-cyber-cyan">backend/.env</code> (copy from <code className="text-cyber-cyan">.env.example</code>)</p>
            </section>

            {/* SSH Hosts */}
            <section>
              <div className="flex items-center gap-2 mb-4">
                <Server className="w-4 h-4 text-cyber-cyan" />
                <h2 className="text-sm font-medium text-text-primary">SSH Hosts</h2>
              </div>
              <div className="bg-bg-secondary border border-border-dim rounded-lg p-4">
                <p className="text-xs text-text-muted">
                  Configure SSH hosts and their command whitelists in{" "}
                  <code className="text-cyber-cyan">config/hosts.yaml</code>.
                  Each host requires an explicit list of allowed commands — the agent cannot execute
                  arbitrary commands.
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
