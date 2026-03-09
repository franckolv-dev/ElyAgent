"use client";

import { useEffect, useState } from "react";
import { AuthGuard } from "@/components/layout/AuthGuard";
import { Sidebar } from "@/components/layout/Sidebar";
import { Header } from "@/components/layout/Header";
import { api } from "@/lib/api";
import { Server, Terminal, Clock, AlertCircle } from "lucide-react";
import type { SSHHost, AuditLog } from "@/lib/types";
import { motion } from "framer-motion";

export default function DashboardPage() {
  const [hosts, setHosts] = useState<Record<string, SSHHost>>({});
  const [logs, setLogs] = useState<AuditLog[]>([]);

  useEffect(() => {
    api.getHosts().then(setHosts).catch(() => {});
    api.getAuditLogs(10).then(setLogs).catch(() => {});
  }, []);

  const hostEntries = Object.entries(hosts);

  return (
    <AuthGuard>
      <div className="flex h-screen overflow-hidden">
        <Sidebar />
        <div className="flex flex-col flex-1 overflow-hidden">
          <Header />
          <div className="flex-1 overflow-y-auto p-6 space-y-6">

            {/* Stats row */}
            <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
              {[
                { label: "Hosts", value: hostEntries.length, icon: Server, color: "cyber-green" },
                { label: "Commands Today", value: logs.filter(l => l.action === "ssh_command").length, icon: Terminal, color: "cyber-cyan" },
                { label: "Recent Actions", value: logs.length, icon: Clock, color: "cyber-blue" },
                { label: "Blocked", value: logs.filter(l => l.result_code !== 0 && l.result_code !== null).length, icon: AlertCircle, color: "cyber-red" },
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
                </motion.div>
              ))}
            </div>

            {/* Hosts grid */}
            <div>
              <h2 className="text-xs text-text-muted uppercase tracking-wider mb-3">Configured Hosts</h2>
              {hostEntries.length === 0 ? (
                <div className="bg-bg-secondary border border-dashed border-border-dim rounded-lg p-8 text-center">
                  <Server className="w-6 h-6 text-text-muted mx-auto mb-2" />
                  <p className="text-sm text-text-muted">No hosts configured yet.</p>
                  <p className="text-xs text-text-muted mt-1">Edit <code className="text-cyber-green">config/hosts.yaml</code> to add SSH hosts.</p>
                </div>
              ) : (
                <div className="grid grid-cols-1 lg:grid-cols-2 xl:grid-cols-3 gap-4">
                  {hostEntries.map(([name, host]) => (
                    <div key={name} className="bg-bg-secondary border border-border-dim rounded-lg p-4">
                      <div className="flex items-center gap-2 mb-3">
                        <div className="w-2 h-2 rounded-full bg-cyber-green animate-pulse-slow" />
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
                          <span>Allowed commands</span>
                          <span className="text-cyber-green">{host.allowed_commands.length}</span>
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>

            {/* Recent activity */}
            <div>
              <h2 className="text-xs text-text-muted uppercase tracking-wider mb-3">Recent Activity</h2>
              {logs.length === 0 ? (
                <div className="bg-bg-secondary border border-border-dim rounded-lg p-6 text-center text-sm text-text-muted">
                  No activity yet.
                </div>
              ) : (
                <div className="bg-bg-secondary border border-border-dim rounded-lg divide-y divide-border-dim">
                  {logs.map((log) => (
                    <div key={log.id} className="flex items-center gap-3 px-4 py-3 text-xs">
                      <span className="text-text-muted shrink-0">
                        {new Date(log.created_at).toLocaleTimeString()}
                      </span>
                      <span className={`px-1.5 py-0.5 rounded text-[10px] uppercase font-medium ${
                        log.action === "ssh_command" ? "bg-cyber-cyan/10 text-cyber-cyan" : "bg-cyber-blue/10 text-cyber-blue"
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
                        <span className={log.result_code === 0 ? "text-cyber-green" : "text-cyber-red"}>
                          [{log.result_code}]
                        </span>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </div>

          </div>
        </div>
      </div>
    </AuthGuard>
  );
}
