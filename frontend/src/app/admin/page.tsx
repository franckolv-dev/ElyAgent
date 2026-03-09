"use client";

import { useEffect, useState } from "react";
import { AuthGuard } from "@/components/layout/AuthGuard";
import { Sidebar } from "@/components/layout/Sidebar";
import { Header } from "@/components/layout/Header";
import { api } from "@/lib/api";
import type { AuditLog } from "@/lib/types";
import { Shield, Users, Terminal, RefreshCw } from "lucide-react";

interface AdminUser {
  id: string;
  username: string;
  email: string;
  role: string;
  is_active: boolean;
  created_at: string;
}

export default function AdminPage() {
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [logs, setLogs] = useState<AuditLog[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [tab, setTab] = useState<"users" | "audit">("audit");

  const load = async () => {
    setLoading(true);
    try {
      const [u, l] = await Promise.all([api.getUsers(), api.getAuditLogs(100)]);
      setUsers(u);
      setLogs(l);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Access denied — admin required");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, []);

  return (
    <AuthGuard>
      <div className="flex h-screen overflow-hidden">
        <Sidebar />
        <div className="flex flex-col flex-1 overflow-hidden">
          <Header />
          <div className="flex-1 overflow-y-auto p-6 space-y-4">

            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <Shield className="w-4 h-4 text-cyber-green" />
                <h1 className="text-sm font-medium text-text-primary">Administration</h1>
              </div>
              <button
                onClick={load}
                className="flex items-center gap-1.5 text-xs text-text-muted hover:text-text-primary transition-colors"
              >
                <RefreshCw className="w-3.5 h-3.5" />
                Refresh
              </button>
            </div>

            {error && (
              <div className="bg-cyber-red/5 border border-cyber-red/20 rounded-lg px-4 py-3 text-sm text-cyber-red">
                {error}
              </div>
            )}

            {/* Tabs */}
            <div className="flex rounded-lg bg-bg-primary border border-border-dim p-1 w-fit">
              {([
                { id: "audit", label: "Audit Logs", icon: Terminal },
                { id: "users", label: "Users", icon: Users },
              ] as const).map(({ id, label, icon: Icon }) => (
                <button
                  key={id}
                  onClick={() => setTab(id)}
                  className={`flex items-center gap-1.5 px-4 py-1.5 rounded-md text-xs transition-all ${
                    tab === id
                      ? "bg-cyber-green/10 text-cyber-green border border-cyber-green/20"
                      : "text-text-muted hover:text-text-secondary"
                  }`}
                >
                  <Icon className="w-3.5 h-3.5" />
                  {label}
                </button>
              ))}
            </div>

            {/* Content */}
            {loading ? (
              <div className="text-sm text-text-muted py-8 text-center">Loading...</div>
            ) : tab === "audit" ? (
              <div className="bg-bg-secondary border border-border-dim rounded-lg overflow-hidden">
                <div className="overflow-x-auto">
                  <table className="w-full text-xs">
                    <thead>
                      <tr className="border-b border-border-dim text-text-muted">
                        <th className="text-left px-4 py-3 font-medium">Time</th>
                        <th className="text-left px-4 py-3 font-medium">Action</th>
                        <th className="text-left px-4 py-3 font-medium">Host</th>
                        <th className="text-left px-4 py-3 font-medium">Command</th>
                        <th className="text-left px-4 py-3 font-medium">Result</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-border-dim">
                      {logs.length === 0 ? (
                        <tr><td colSpan={5} className="px-4 py-8 text-center text-text-muted">No audit logs yet.</td></tr>
                      ) : logs.map((log) => (
                        <tr key={log.id} className="hover:bg-bg-tertiary/50">
                          <td className="px-4 py-2.5 text-text-muted whitespace-nowrap">
                            {new Date(log.created_at).toLocaleString()}
                          </td>
                          <td className="px-4 py-2.5">
                            <span className="px-1.5 py-0.5 rounded text-[10px] uppercase bg-cyber-cyan/10 text-cyber-cyan">
                              {log.action}
                            </span>
                          </td>
                          <td className="px-4 py-2.5 text-text-secondary">{log.target_host ?? "—"}</td>
                          <td className="px-4 py-2.5 font-mono text-text-primary max-w-xs truncate">
                            {log.command ?? "—"}
                          </td>
                          <td className="px-4 py-2.5">
                            {log.result_code !== null ? (
                              <span className={log.result_code === 0 ? "text-cyber-green" : "text-cyber-red"}>
                                [{log.result_code}]
                              </span>
                            ) : "—"}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            ) : (
              <div className="bg-bg-secondary border border-border-dim rounded-lg overflow-hidden">
                <table className="w-full text-xs">
                  <thead>
                    <tr className="border-b border-border-dim text-text-muted">
                      <th className="text-left px-4 py-3 font-medium">Username</th>
                      <th className="text-left px-4 py-3 font-medium">Email</th>
                      <th className="text-left px-4 py-3 font-medium">Role</th>
                      <th className="text-left px-4 py-3 font-medium">Status</th>
                      <th className="text-left px-4 py-3 font-medium">Created</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-border-dim">
                    {users.map((u) => (
                      <tr key={u.id} className="hover:bg-bg-tertiary/50">
                        <td className="px-4 py-2.5 text-text-primary font-medium">{u.username}</td>
                        <td className="px-4 py-2.5 text-text-secondary">{u.email}</td>
                        <td className="px-4 py-2.5">
                          <span className={`px-1.5 py-0.5 rounded text-[10px] uppercase ${
                            u.role === "admin"
                              ? "bg-cyber-purple/10 text-cyber-purple"
                              : "bg-bg-tertiary text-text-muted"
                          }`}>
                            {u.role}
                          </span>
                        </td>
                        <td className="px-4 py-2.5">
                          <span className={`px-1.5 py-0.5 rounded text-[10px] ${
                            u.is_active ? "text-cyber-green" : "text-cyber-red"
                          }`}>
                            {u.is_active ? "active" : "disabled"}
                          </span>
                        </td>
                        <td className="px-4 py-2.5 text-text-muted">
                          {new Date(u.created_at).toLocaleDateString()}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </div>
      </div>
    </AuthGuard>
  );
}
