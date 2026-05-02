"use client";
/**
 * @project    ELY — Exactly Like You
 * @file       frontend/src/app/dashboard/page.tsx
 * @brief      Dashboard page — activity overview and quick actions
 *
 * @author     Franck OLLIVIER <contact@agent-ely.fr>
 * @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
 * @license    PolyForm Strict License 1.0.0
 *             https://polyformproject.org/licenses/strict/1.0.0/
 * @version    1.1.0
 * @link       https://github.com/franckolv-dev/PhysicalAgent
 *
 * RÉSUMÉ DES CONDITIONS :
 *   - AUTORISÉ : Utilisation personnelle, éducative et tests privés.
 *   - INTERDIT : Toute utilisation commerciale sans accord préalable.
 *   - INTERDIT : Redistribution de versions modifiées de ce code.
 */

import { useEffect, useState, useCallback } from "react";
import { AdminGuard } from "@/components/layout/AuthGuard";
import { Sidebar } from "@/components/layout/Sidebar";
import { Header } from "@/components/layout/Header";
import { api } from "@/lib/api";
import { authFetch } from "@/lib/auth";
import { Server, Terminal, Clock, AlertCircle, TrendingUp, Zap, DollarSign, BarChart2 } from "lucide-react";
import { motion } from "framer-motion";
import type { AuditLog, SSHHost } from "@/lib/types";
import { useTranslations } from "next-intl";

// ── Types ────────────────────────────────────────────────────────────────────

interface AnalyticsSummary {
  total_requests: number;
  total_tokens: number;
  total_cost_usd: number;
  input_tokens: number;
  output_tokens: number;
  period_days: number;
}

interface DailyUsage {
  day: string;
  requests: number;
  tokens: number;
  cost: number;
}

interface SkillUsage {
  skill: string;
  count: number;
  tokens: number;
}

interface HitlStats {
  allow: number;
  deny: number;
  ban: number;
}

interface ProviderUsage {
  provider: string;
  model: string;
  requests: number;
  tokens: number;
  cost: number;
}

// ── Helpers ──────────────────────────────────────────────────────────────────

function formatNumber(n: number): string {
  if (n >= 1_000_000) return (n / 1_000_000).toFixed(1) + "M";
  if (n >= 1_000) return (n / 1_000).toFixed(1) + "K";
  return String(n);
}

function formatCost(n: number): string {
  if (n < 0.001) return "$0.00";
  if (n < 0.01) return `$${n.toFixed(4)}`;
  if (n < 1) return `$${n.toFixed(3)}`;
  return `$${n.toFixed(2)}`;
}

// ── SVG Bar Chart ─────────────────────────────────────────────────────────────

function BarChart({ data, height = 120, noDataLabel }: { data: DailyUsage[]; height?: number; noDataLabel: string }) {
  if (!data.length) return (
    <div className="flex items-center justify-center h-32 text-text-muted text-sm">
      {noDataLabel}
    </div>
  );

  const maxTokens = Math.max(...data.map((d) => d.tokens), 1);
  const barWidth = Math.max(4, Math.floor(500 / data.length) - 2);
  const gap = 2;
  const totalWidth = data.length * (barWidth + gap);

  return (
    <div className="overflow-x-auto">
      <svg
        width={Math.max(totalWidth, 500)}
        height={height + 30}
        className="text-cyber-cyan"
      >
        {data.map((d, i) => {
          const barH = Math.max(2, (d.tokens / maxTokens) * height);
          const x = i * (barWidth + gap);
          const y = height - barH;
          const isRecent = i >= data.length - 7;
          return (
            <g key={d.day}>
              <rect
                x={x}
                y={y}
                width={barWidth}
                height={barH}
                className={isRecent ? "fill-cyber-cyan" : "fill-cyber-cyan/40"}
                rx={2}
              >
                <title>{`${d.day}: ${formatNumber(d.tokens)} tokens, ${d.requests} req, ${formatCost(d.cost)}`}</title>
              </rect>
            </g>
          );
        })}
        {/* X-axis line */}
        <line
          x1={0} y1={height} x2={totalWidth} y2={height}
          stroke="currentColor" strokeOpacity={0.2} strokeWidth={1}
        />
      </svg>
      <div className="flex justify-between text-xs text-text-muted mt-1">
        <span>{data[0]?.day?.slice(5)}</span>
        <span>{data[Math.floor(data.length / 2)]?.day?.slice(5)}</span>
        <span>{data[data.length - 1]?.day?.slice(5)}</span>
      </div>
    </div>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────

export default function DashboardPage() {
  const t = useTranslations("dashboard");
  const [period, setPeriod] = useState(30);
  const [summary, setSummary] = useState<AnalyticsSummary | null>(null);
  const [daily, setDaily] = useState<DailyUsage[]>([]);
  const [skills, setSkills] = useState<SkillUsage[]>([]);
  const [hitl, setHitl] = useState<HitlStats | null>(null);
  const [providers, setProviders] = useState<ProviderUsage[]>([]);
  const [hosts, setHosts] = useState<Record<string, SSHHost>>({});
  const [logs, setLogs] = useState<AuditLog[]>([]);
  const [loading, setLoading] = useState(true);

  const fetchAnalytics = useCallback(async (days: number) => {
    setLoading(true);
    try {
      const base = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

      const [sumRes, dailyRes, skillsRes, hitlRes, providersRes] = await Promise.all([
        authFetch(`${base}/analytics/summary?days=${days}`),
        authFetch(`${base}/analytics/daily?days=${days}`),
        authFetch(`${base}/analytics/skills?days=${days}`),
        authFetch(`${base}/analytics/hitl?days=${days}`),
        authFetch(`${base}/analytics/providers?days=${days}`),
      ]);

      if (sumRes.ok) setSummary(await sumRes.json());
      if (dailyRes.ok) setDaily(await dailyRes.json());
      if (skillsRes.ok) setSkills(await skillsRes.json());
      if (hitlRes.ok) setHitl(await hitlRes.json());
      if (providersRes.ok) setProviders(await providersRes.json());
    } catch (e) {
      // Analytics API not yet available — show empty state gracefully
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchAnalytics(period);
    api.getHosts().then(setHosts).catch(() => {});
    api.getAuditLogs(10).then(setLogs).catch(() => {});
  }, [period, fetchAnalytics]);

  const hostEntries = Object.entries(hosts);
  const maxSkillCount = Math.max(...skills.map((s) => s.count), 1);
  const totalHitl = (hitl?.allow ?? 0) + (hitl?.deny ?? 0) + (hitl?.ban ?? 0);

  return (
    <AdminGuard>
      <div className="flex flex-col h-screen overflow-hidden">
        <Header />
        <div className="flex flex-1 overflow-hidden">
          <Sidebar />
          <main className="flex-1 overflow-y-auto p-6 space-y-6" style={{ background: "var(--bg-app)" }}>

            {/* Period selector */}
            <div className="flex items-center justify-between">
              <h1 className="text-lg font-medium text-text-primary">{t("title")}</h1>
              <div className="flex gap-1 bg-bg-secondary border border-border-dim rounded-lg p-1">
                {[7, 30, 90].map((d) => (
                  <button
                    key={d}
                    onClick={() => setPeriod(d)}
                    className={`px-3 py-1 text-xs rounded transition-colors ${
                      period === d
                        ? "bg-cyber-cyan text-bg-primary font-medium"
                        : "text-text-muted hover:text-text-primary"
                    }`}
                  >
                    {d}j
                  </button>
                ))}
              </div>
            </div>

            {/* Analytics stats */}
            <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
              {[
                {
                  label: t("requests"),
                  value: summary ? formatNumber(summary.total_requests) : "—",
                  icon: TrendingUp,
                  color: "cyber-cyan",
                  sub: `${period} derniers jours`,
                },
                {
                  label: t("tokens"),
                  value: summary ? formatNumber(summary.total_tokens) : "—",
                  icon: Zap,
                  color: "cyber-cyan",
                  sub: summary
                    ? `${formatNumber(summary.input_tokens)} in / ${formatNumber(summary.output_tokens)} out`
                    : "",
                },
                {
                  label: t("estimatedCost"),
                  value: summary ? formatCost(summary.total_cost_usd) : "—",
                  icon: DollarSign,
                  color: "cyber-blue",
                  sub: "estimation approximative",
                },
                {
                  label: t("sshHosts"),
                  value: hostEntries.length,
                  icon: Server,
                  color: "cyber-cyan",
                  sub: `${logs.filter((l) => l.action === "ssh_command").length} cmd aujourd'hui`,
                },
              ].map((stat, i) => (
                <motion.div
                  key={stat.label}
                  initial={{ opacity: 0, y: 10 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ delay: i * 0.05 }}
                  className="bg-bg-secondary border border-border-dim rounded-lg p-4"
                >
                  <div className="flex items-center justify-between mb-2">
                    <span className="text-xs text-text-muted uppercase tracking-wider">{stat.label}</span>
                    <stat.icon className={`w-4 h-4 text-${stat.color}`} />
                  </div>
                  <div className={`text-2xl font-bold text-${stat.color}`}>{stat.value}</div>
                  <div className="text-xs text-text-muted mt-1">{stat.sub}</div>
                </motion.div>
              ))}
            </div>

            {/* Daily usage chart */}
            <div className="bg-bg-secondary border border-border-dim rounded-lg p-4">
              <div className="flex items-center gap-2 mb-4">
                <BarChart2 className="w-4 h-4 text-cyber-cyan" />
                <h2 className="text-xs text-text-muted uppercase tracking-wider">
                  {t("tokensPerDay")}
                </h2>
              </div>
              {loading ? (
                <div className="h-32 flex items-center justify-center text-text-muted text-sm animate-pulse">
                  {t("loading")}
                </div>
              ) : (
                <BarChart data={daily} noDataLabel={t("noData")} />
              )}
            </div>

            <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
              {/* Top skills */}
              <div className="bg-bg-secondary border border-border-dim rounded-lg p-4">
                <h2 className="text-xs text-text-muted uppercase tracking-wider mb-4">
                  {t("mostUsedSkills")}
                </h2>
                {skills.length === 0 ? (
                  <p className="text-sm text-text-muted text-center py-4">{t("noData")}</p>
                ) : (
                  <div className="space-y-2">
                    {skills.map((s) => (
                      <div key={s.skill} className="space-y-1">
                        <div className="flex justify-between text-xs">
                          <span className="text-text-secondary">{s.skill}</span>
                          <span className="text-text-muted">{s.count}×</span>
                        </div>
                        <div className="h-1.5 bg-bg-primary rounded-full overflow-hidden">
                          <div
                            className="h-full bg-cyber-cyan rounded-full transition-all"
                            style={{ width: `${(s.count / maxSkillCount) * 100}%` }}
                          />
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>

              {/* HITL stats */}
              <div className="bg-bg-secondary border border-border-dim rounded-lg p-4">
                <h2 className="text-xs text-text-muted uppercase tracking-wider mb-4">
                  {t("hitlValidations")}
                </h2>
                {!hitl || totalHitl === 0 ? (
                  <p className="text-sm text-text-muted text-center py-4">Aucune validation</p>
                ) : (
                  <div className="space-y-3">
                    {[
                      { label: "✅ Autorisées", value: hitl.allow, color: "bg-emerald-500" },
                      { label: "❌ Refusées", value: hitl.deny, color: "bg-amber-500" },
                      { label: "🚫 Interdites", value: hitl.ban, color: "bg-red-500" },
                    ].map((item) => (
                      <div key={item.label} className="space-y-1">
                        <div className="flex justify-between text-xs">
                          <span className="text-text-secondary">{item.label}</span>
                          <span className="text-text-muted">
                            {item.value} ({totalHitl ? Math.round((item.value / totalHitl) * 100) : 0}%)
                          </span>
                        </div>
                        <div className="h-2 bg-bg-primary rounded-full overflow-hidden">
                          <div
                            className={`h-full ${item.color} rounded-full transition-all`}
                            style={{ width: `${totalHitl ? (item.value / totalHitl) * 100 : 0}%` }}
                          />
                        </div>
                      </div>
                    ))}
                    <div className="pt-2 border-t border-border-dim text-xs text-text-muted">
                      Total : {totalHitl} action{totalHitl > 1 ? "s" : ""} validée{totalHitl > 1 ? "s" : ""}
                    </div>
                  </div>
                )}
              </div>
            </div>

            {/* LLM Provider breakdown */}
            <div className="bg-bg-secondary border border-border-dim rounded-lg p-4">
              <h2 className="text-xs text-text-muted uppercase tracking-wider mb-4">
                {t("usageByLlm")}
              </h2>
              {(() => {
                // Exclude hitl-only entries (0 tokens, provider="hitl") from LLM block
                const llmProviders = providers.filter((p) => p.provider !== "hitl" && p.tokens > 0);
                return llmProviders.length === 0 ? (
                <p className="text-sm text-text-muted text-center py-4">{t("noData")}</p>
              ) : (
                <div className="space-y-3">
                  {llmProviders.map((p) => {
                    const maxTokens = Math.max(...llmProviders.map((x) => x.tokens), 1);
                    const PROVIDER_COLORS: Record<string, string> = {
                      anthropic: "bg-cyber-cyan",
                      zhipu:     "bg-violet-500",
                      gemini:    "bg-blue-500",
                      mistral:   "bg-orange-400",
                      deepseek:  "bg-purple-500",
                      ollama:    "bg-emerald-500",
                      moonshot:  "bg-indigo-500",
                    };
                    const color = PROVIDER_COLORS[p.provider] ?? "bg-text-muted";
                    return (
                      <div key={`${p.provider}-${p.model}`} className="space-y-1">
                        <div className="flex justify-between text-xs">
                          <span className="text-text-secondary font-medium">{p.provider}</span>
                          <span className="text-text-muted text-[10px] truncate max-w-[120px]">{p.model}</span>
                          <span className="text-text-muted ml-2">{p.requests} req · {formatCost(p.cost)}</span>
                        </div>
                        <div className="h-1.5 bg-bg-primary rounded-full overflow-hidden">
                          <div
                            className={`h-full ${color} rounded-full transition-all`}
                            style={{ width: `${(p.tokens / maxTokens) * 100}%` }}
                          />
                        </div>
                      </div>
                    );
                  })}
                </div>
              );
              })()}
            </div>

            {/* SSH Hosts */}
            <div>
              <h2 className="text-xs text-text-muted uppercase tracking-wider mb-3">{t("sshConfiguredHosts")}</h2>
              {hostEntries.length === 0 ? (
                <div className="bg-bg-secondary border border-dashed border-border-dim rounded-lg p-8 text-center">
                  <Server className="w-6 h-6 text-text-muted mx-auto mb-2" />
                  <p className="text-sm text-text-muted">{t("noHostsConfigured")}</p>
                  <p className="text-xs text-text-muted mt-1">
                    Éditez <code className="text-cyber-cyan">config/hosts.yaml</code>
                  </p>
                </div>
              ) : (
                <div className="grid grid-cols-1 lg:grid-cols-2 xl:grid-cols-3 gap-4">
                  {hostEntries.map(([name, host]) => (
                    <div key={name} className="bg-bg-secondary border border-border-dim rounded-lg p-4">
                      <div className="flex items-center gap-2 mb-3">
                        <div className="w-2 h-2 rounded-full bg-cyber-cyan animate-pulse-slow" />
                        <span className="text-sm font-medium text-text-primary">{name}</span>
                      </div>
                      <div className="space-y-1 text-xs text-text-muted">
                        <div className="flex justify-between">
                          <span>Host</span>
                          <span className="text-text-secondary">{host.hostname}:{host.port}</span>
                        </div>
                        <div className="flex justify-between">
                          <span>User</span>
                          <span className="text-text-secondary">{host.username}</span>
                        </div>
                        <div className="flex justify-between">
                          <span>Commandes autorisées</span>
                          <span className="text-cyber-cyan">{host.allowed_commands.length}</span>
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>

            {/* Recent activity */}
            <div>
              <h2 className="text-xs text-text-muted uppercase tracking-wider mb-3">{t("recentActivity")}</h2>
              {logs.length === 0 ? (
                <div className="bg-bg-secondary border border-border-dim rounded-lg p-6 text-center text-sm text-text-muted">
                  {t("noRecentActivity")}
                </div>
              ) : (
                <div className="bg-bg-secondary border border-border-dim rounded-lg divide-y divide-border-dim">
                  {logs.map((log) => (
                    <div key={log.id} className="flex items-center gap-3 px-4 py-3 text-xs">
                      <span className="text-text-muted shrink-0">
                        {new Date(log.created_at).toLocaleTimeString()}
                      </span>
                      <span className={`px-1.5 py-0.5 rounded text-[10px] uppercase font-medium ${
                        log.action === "ssh_command"
                          ? "bg-cyber-cyan/10 text-cyber-cyan"
                          : "bg-cyber-blue/10 text-cyber-blue"
                      }`}>
                        {log.action}
                      </span>
                      {log.target_host && (
                        <span className="text-text-secondary">{log.target_host}</span>
                      )}
                      {log.command && (
                        <code className="text-text-primary truncate flex-1">{log.command}</code>
                      )}
                      {log.result_code !== null && (
                        <span className={log.result_code === 0 ? "text-cyber-cyan" : "text-cyber-red"}>
                          [{log.result_code}]
                        </span>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </div>

          </main>
        </div>
      </div>
    </AdminGuard>
  );
}
